"""
Telegram-бот обмена RUB → USDT.

Запуск:
  1. Создай бота у @BotFather
  2. Скопируй .env.example → .env и заполни BOT_TOKEN, ADMIN_IDS, SUPPORT_IDS
  3. pip install -r requirements.txt
  4. python bot.py
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonCommands
from dotenv import load_dotenv

from exchange.config import load_settings
from exchange.context import AppContext, ContextMiddleware
from exchange.db import Database
from exchange.handlers import setup_routers
from exchange.rates import RateService
from exchange.rates.samples import RateSampleStore
from exchange.rates.service import default_samples_path
from exchange.receipt import build_receipt_checker
from exchange.services import OrderService

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def expire_loop(orders: OrderService, bot: Bot, interval_sec: int = 60) -> None:
    while True:
        try:
            expired = await orders.expire_overdue()
            for order in expired:
                try:
                    await bot.send_message(
                        order.client_tg_id,
                        f"⏰ Время оплаты по заявке <b>{order.public_id}</b> истекло.\n"
                        "Создайте новую заявку, если обмен ещё актуален.",
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.exception("expire notify failed for %s", order.public_id)
        except Exception:
            logger.exception("expire_loop error")
        await asyncio.sleep(interval_sec)


async def rates_loop(rates: RateService, interval_sec: int) -> None:
    while True:
        try:
            await rates.refresh()
        except Exception:
            logger.exception("rates_loop error")
        await asyncio.sleep(max(15, interval_sec))


async def main() -> None:
    settings = load_settings()
    if not settings.bot_token:
        raise SystemExit(
            "Не задан BOT_TOKEN.\n"
            "Создайте бота у @BotFather и пропишите токен в .env"
        )
    if not settings.admin_ids:
        logger.warning("ADMIN_IDS пуст — выплачивать USDT через /admin будет некому")

    db = Database(settings.database_path)
    await db.connect()
    samples = RateSampleStore(default_samples_path(settings.database_path))
    await samples.connect()
    receipt_checker = build_receipt_checker(settings)
    rate_service = RateService(settings, samples=samples)
    await rate_service.refresh()
    order_service = OrderService(
        db=db,
        settings=settings,
        receipt_checker=receipt_checker,
        rates=rate_service,
    )
    ctx = AppContext(
        settings=settings, db=db, orders=order_service, rates=rate_service
    )

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(ContextMiddleware(ctx))
    setup_routers(dp)

    # Меню команд слева от поля ввода в Telegram (без обязательного набора /start)
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Открыть меню"),
            BotCommand(command="menu", description="Открыть меню"),
            BotCommand(command="exchange", description="Новая заявка"),
            BotCommand(command="orders", description="Мои заявки"),
            BotCommand(command="rate", description="Курс"),
            BotCommand(command="help", description="Помощь"),
            BotCommand(command="support", description="Панель саппорта"),
            BotCommand(command="admin", description="Панель администратора"),
        ]
    )
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    expire_task = asyncio.create_task(expire_loop(order_service, bot))
    rates_task = asyncio.create_task(
        rates_loop(rate_service, settings.rate_refresh_sec)
    )

    me = await bot.get_me()
    snap = rate_service.snapshot()
    logger.info(
        "Exchange bot @%s started; client_rate=%.4f mode=%s receipt=%s db=%s",
        me.username,
        snap.client,
        snap.mode,
        settings.receipt_provider,
        settings.database_path,
    )
    try:
        await dp.start_polling(bot)
    finally:
        expire_task.cancel()
        rates_task.cancel()
        await samples.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
