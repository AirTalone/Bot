from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from exchange.config import Settings
from exchange.keyboards import client_main_kb

router = Router(name="common")

HELP_TEXT = (
    "Это бот обмена <b>RUB → USDT</b>.\n\n"
    "Как это работает:\n"
    "1) Создаёте заявку (сумма + адрес USDT)\n"
    "2) Саппорт подбирает реквизиты под вашу сумму\n"
    "3) Оплачиваете и загружаете чек (PDF/фото)\n"
    "4) Чек проходит автопроверку, затем саппорт подтверждает\n"
    "5) Администратор отправляет USDT на ваш адрес\n\n"
    "Команды:\n"
    "/start — меню\n"
    "/exchange — новая заявка\n"
    "/orders — мои заявки\n"
    "/rate — текущий курс\n"
    "/support — панель саппорта\n"
    "/admin — панель администратора\n"
    "/qr — сделать QR из ссылки СБП (утилита)"
)


@router.message(CommandStart())
async def cmd_start(message: Message, settings: Settings) -> None:
    role_bits = []
    if message.from_user and settings.is_admin(message.from_user.id):
        role_bits.append("админ")
    elif message.from_user and settings.is_support(message.from_user.id):
        role_bits.append("саппорт")
    extra = f"\nВаша роль: {', '.join(role_bits)}" if role_bits else ""
    await message.answer(
        "Привет! Обмен рублей на USDT через заявки." + extra + "\n\n" + HELP_TEXT,
        reply_markup=client_main_kb(),
        parse_mode="HTML",
    )


@router.message(Command("help"))
@router.message(F.text == "Помощь")
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, parse_mode="HTML", reply_markup=client_main_kb())


@router.message(Command("rate"))
@router.message(F.text == "Курс")
async def cmd_rate(message: Message, settings: Settings) -> None:
    await message.answer(
        f"Базовый курс: <b>{settings.usdt_rate_rub:.4f}</b> ₽/USDT\n"
        f"Спред: <b>{settings.spread_percent:.2f}%</b>\n"
        f"Курс для клиента: <b>{settings.effective_rate():.4f}</b> ₽/USDT\n"
        f"Лимиты: {settings.min_amount_rub:.0f}–{settings.max_amount_rub:.0f} ₽",
        parse_mode="HTML",
    )
