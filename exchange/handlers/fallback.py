"""Если пользователь пишет что угодно вне сценария — показываем меню (как /start)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.state import default_state
from aiogram.types import Message

from exchange.config import Settings
from exchange.handlers.common import welcome_text
from exchange.keyboards import client_main_kb

router = Router(name="fallback")


@router.message(StateFilter(default_state), F.text)
async def any_text_shows_menu(message: Message, settings: Settings, rates) -> None:
    # Не перехватываем уже обработанные кнопки/команды — этот роутер подключается последним.
    user_id = message.from_user.id if message.from_user else None
    await message.answer(
        welcome_text(settings, user_id, rates),
        reply_markup=client_main_kb(),
        parse_mode="HTML",
    )


@router.message(StateFilter(default_state))
async def any_other_shows_menu(message: Message, settings: Settings, rates) -> None:
    user_id = message.from_user.id if message.from_user else None
    await message.answer(
        "Пользуйтесь кнопками внизу.\n\n"
        + welcome_text(settings, user_id, rates),
        reply_markup=client_main_kb(),
        parse_mode="HTML",
    )
