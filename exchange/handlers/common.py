from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.state import default_state
from aiogram.types import Message

from exchange.config import Settings
from exchange.keyboards import client_main_kb

router = Router(name="common")

HELP_TEXT = (
    "Это бот обмена <b>RUB → USDT</b>.\n\n"
    "Как это работает:\n"
    "1) Создаёте заявку (сумма; адрес USDT можно указать сразу или позже)\n"
    "2) Саппорт подбирает реквизиты под вашу сумму\n"
    "3) Оплачиваете и загружаете чек (PDF/фото)\n"
    "4) Чек проходит автопроверку, затем саппорт подтверждает\n"
    "5) Администратор отправляет USDT на ваш адрес"
)


def welcome_text(settings: Settings, user_id: int | None) -> str:
    role_bits = []
    if user_id is not None and settings.is_admin(user_id):
        role_bits.append("админ")
    elif user_id is not None and settings.is_support(user_id):
        role_bits.append("саппорт")
    extra = f"\nВаша роль: {', '.join(role_bits)}" if role_bits else ""
    return "Привет! Обмен рублей на USDT через заявки." + extra + "\n\n" + HELP_TEXT



@router.message(CommandStart())
@router.message(Command("menu"))
@router.message(F.text == "Меню")
async def cmd_start(message: Message, settings: Settings) -> None:
    user_id = message.from_user.id if message.from_user else None
    await message.answer(
        welcome_text(settings, user_id),
        reply_markup=client_main_kb(),
        parse_mode="HTML",
    )


@router.message(Command("help"))
@router.message(F.text == "Помощь")
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, parse_mode="HTML", reply_markup=client_main_kb())


@router.message(Command("rate"))
@router.message(F.text == "Курс")
async def cmd_rate(message: Message, settings: Settings, rates) -> None:
    snap = rates.snapshot()
    await message.answer(
        snap.summary_html()
        + f"\nСпред: <b>{settings.spread_percent:.2f}%</b>"
        + f"\nЛимиты: {settings.min_amount_rub:.0f}–{settings.max_amount_rub:.0f} ₽",
        parse_mode="HTML",
        reply_markup=client_main_kb(),
    )
