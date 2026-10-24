import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, ErrorEvent
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import Settings, get_settings
from bot.db import create_engine, create_session_factory, ensure_sqlite_parent, prepare_runtime_db
from bot.handlers import admin_router, user_router
from bot.middlewares import DbSessionMiddleware
from bot.services.reminders import process_reminders

logger = logging.getLogger(__name__)


async def setup_commands(bot: Bot, settings: Settings) -> None:
    user_commands = [
        BotCommand(command="start", description="Тарифы"),
        BotCommand(command="orders", description="Мои заказы"),
        BotCommand(command="help", description="Инструкция"),
        BotCommand(command="faq", description="FAQ"),
    ]
    await bot.set_my_commands(user_commands)
    admin_commands = [
        *user_commands,
        BotCommand(command="admin", description="Заявки на оплату"),
    ]
    for admin_id in settings.admin_id_list:
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except TelegramAPIError:
            logger.warning("failed to set commands for admin %s", admin_id)


async def reminder_loop(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    interval = max(60, settings.reminder_interval_seconds)
    while True:
        try:
            reminded, expired = await process_reminders(
                bot,
                session_factory,
                days_before=max(1, settings.reminder_days_before),
            )
            if reminded or expired:
                logger.info("reminders sent=%s expired_notices=%s", reminded, expired)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("reminder loop failed")
        await asyncio.sleep(interval)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    token = settings.require_bot_token()
    if not settings.admin_id_list:
        logger.warning("ADMIN_IDS is empty; payment claims will stay in /admin without a push")

    ensure_sqlite_parent(settings.database_url)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    await prepare_runtime_db(
        engine,
        session_factory,
        database_url=settings.database_url,
        auto_create_sqlite=settings.auto_create_sqlite,
    )

    dispatcher = Dispatcher(storage=MemoryStorage(), settings=settings)
    dispatcher.update.middleware(DbSessionMiddleware(session_factory))
    dispatcher.include_router(admin_router)
    dispatcher.include_router(user_router)

    @dispatcher.errors()
    async def on_error(event: ErrorEvent) -> None:
        logger.exception("update handling failed", exc_info=event.exception)

    reminder_task: asyncio.Task[None] | None = None
    try:
        async with Bot(
            token=token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        ) as bot:
            await setup_commands(bot, settings)
            reminder_task = asyncio.create_task(
                reminder_loop(bot, session_factory, settings),
                name="reminder-loop",
            )
            await dispatcher.start_polling(bot)
    finally:
        if reminder_task is not None:
            reminder_task.cancel()
            try:
                await reminder_task
            except asyncio.CancelledError:
                pass
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
