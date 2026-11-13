"""Панель сотрудников: «Взять» / «Отпустить», /stats, /chatid."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from exchange.config import Settings
from exchange.db import Database
from exchange.staff_panel import StaffPanel, display_name
from exchange.stats import build_stats_text

logger = logging.getLogger(__name__)
router = Router(name="staff")


@router.callback_query(F.data.startswith("staff:take:"))
async def staff_take(
    callback: CallbackQuery, settings: Settings, db: Database, panel: StaffPanel
) -> None:
    if not settings.is_support(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    order = await db.get_order_by_id(int(callback.data.split(":")[-1]))  # type: ignore[union-attr]
    if order is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    owner = await db.take_order(
        order.id, tg_id=callback.from_user.id, name=display_name(callback.from_user)
    )
    if owner[0] != callback.from_user.id:
        await callback.answer(f"Заявку уже ведёт {owner[1]}", show_alert=True)
        return
    await panel.sync(order)
    await callback.answer("Заявка ваша ✅")


@router.callback_query(F.data.startswith("staff:release:"))
async def staff_release(
    callback: CallbackQuery, settings: Settings, db: Database, panel: StaffPanel
) -> None:
    if not settings.is_support(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    order = await db.get_order_by_id(int(callback.data.split(":")[-1]))  # type: ignore[union-attr]
    if order is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    owner = await db.get_owner(order.id)
    if owner is None:
        await callback.answer("Заявка и так свободна")
        return
    if owner[0] != callback.from_user.id and not settings.is_admin(callback.from_user.id):
        await callback.answer(f"Отпустить может только {owner[1]} или админ", show_alert=True)
        return
    await db.release_order(order.id)
    await panel.sync(order)
    await callback.answer("Заявка снова свободна")


@router.message(Command("stats"))
async def cmd_stats(message: Message, settings: Settings, db: Database) -> None:
    if message.from_user is None or not settings.is_support(message.from_user.id):
        return
    await message.answer(await build_stats_text(db), parse_mode="HTML")


@router.message(Command("chatid"))
async def cmd_chatid(message: Message, settings: Settings) -> None:
    """Подсказка ID группы для STAFF_CHAT_ID."""
    if message.from_user is None or not settings.is_support(message.from_user.id):
        return
    await message.answer(
        f"ID этого чата: <code>{message.chat.id}</code>\n"
        "Впишите его в настройки: <code>STAFF_CHAT_ID=" f"{message.chat.id}</code>",
        parse_mode="HTML",
    )


@router.my_chat_member()
async def bot_added_to_chat(event: ChatMemberUpdated) -> None:
    """Бота добавили в группу — пишем ID в лог."""
    if event.chat.type in {"group", "supergroup"}:
        logger.info(
            "Бот в группе «%s»: chat_id=%s, статус=%s",
            event.chat.title,
            event.chat.id,
            event.new_chat_member.status,
        )
