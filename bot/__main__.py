import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, ErrorEvent

from bot.config import Settings, get_settings
from bot.db import create_engine, create_session_factory, ensure_sqlite_parent, init_db
from bot.handlers import admin_router, user_router
from bot.middlewares import DbSessionMiddleware

logger = logging.getLogger(__name__)


async def setup_commands(bot: Bot, settings: Settings) -> None:
    user_commands = [
        BotCommand(command="start", description="Тарифы"),
        BotCommand(command="orders", description="Мои заказы"),
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


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    if not settings.admin_id_list:
        logger.warning("ADMIN_IDS is empty; payment claims will stay in /admin without a push")

    ensure_sqlite_parent(settings.database_url)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    await init_db(engine, session_factory)

    dispatcher = Dispatcher(storage=MemoryStorage(), settings=settings)
    dispatcher.update.middleware(DbSessionMiddleware(session_factory))
    dispatcher.include_router(admin_router)
    dispatcher.include_router(user_router)

    @dispatcher.errors()
    async def on_error(event: ErrorEvent) -> None:
        logger.exception("update handling failed", exc_info=event.exception)

    try:
        async with Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        ) as bot:
            await setup_commands(bot, settings)
            await dispatcher.start_polling(bot)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
