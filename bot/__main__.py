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
from bot.handlers import admin_router, payments_router, user_router
from bot.logging_setup import setup_logging
from bot.middlewares import DbSessionMiddleware
from bot.sentry_setup import setup_sentry
from bot.services.heartbeat import notify_admins_alive, touch_heartbeat
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


async def heartbeat_loop(bot: Bot, settings: Settings) -> None:
    interval = max(5, settings.heartbeat_seconds)
    alert_every = settings.heartbeat_alert_seconds
    last_alert = 0.0
    while True:
        try:
            touch_heartbeat(settings.heartbeat_path)
            now = asyncio.get_running_loop().time()
            if alert_every > 0 and now - last_alert >= alert_every:
                sent = await notify_admins_alive(bot, settings, reason="heartbeat")
                logger.info("heartbeat admin notify sent=%s", sent)
                last_alert = now
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("heartbeat loop failed")
        await asyncio.sleep(interval)


async def main() -> None:
    settings = get_settings()
    setup_logging(json_logs=settings.log_json)
    setup_sentry(settings.sentry_dsn, environment=settings.sentry_environment)
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
    dispatcher.include_router(payments_router)
    dispatcher.include_router(user_router)

    @dispatcher.errors()
    async def on_error(event: ErrorEvent) -> None:
        logger.exception("update handling failed", exc_info=event.exception)

    background: list[asyncio.Task[None]] = []
    try:
        async with Bot(
            token=token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        ) as bot:
            await setup_commands(bot, settings)
            touch_heartbeat(settings.heartbeat_path)
            if settings.heartbeat_startup_notify:
                await notify_admins_alive(bot, settings, reason="startup")
            background.append(
                asyncio.create_task(reminder_loop(bot, session_factory, settings), name="reminder-loop")
            )
            background.append(asyncio.create_task(heartbeat_loop(bot, settings), name="heartbeat-loop"))
            await dispatcher.start_polling(bot)
    finally:
        for task in background:
            task.cancel()
        for task in background:
            try:
                await task
            except asyncio.CancelledError:
                pass
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
