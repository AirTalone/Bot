"""Панель сотрудников: «Взять» / «Отпустить», доверенные клиенты, видео, /stats, /chatid, /trusted."""

from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from exchange.config import Settings
from exchange.db import Database
from exchange.keyboards import support_order_kb
from exchange.services import OrderError, OrderService
from exchange.staff_panel import (
    StaffPanel,
    display_name,
    is_group_callback,
    open_bot_chat,
)
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



@router.callback_query(F.data.startswith("staff:trust:") | F.data.startswith("staff:untrust:"))
async def staff_trust(
    callback: CallbackQuery, settings: Settings, db: Database, orders: OrderService
) -> None:
    """Доверенный клиент: видео перевода не нужно, достаточно PDF-чека."""
    if not settings.is_support(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    _, action, order_id = callback.data.split(":")  # type: ignore[union-attr]
    order = await db.get_order_by_id(int(order_id))
    if order is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    trusted = action == "trust"
    try:
        order = await orders.set_client_trusted(
            order, trusted=trusted, by_tg_id=callback.from_user.id
        )
    except OrderError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    # В группе карточка обновится сама; в личке — меняем кнопки на месте
    if not is_group_callback(callback):
        try:
            await callback.message.edit_reply_markup(  # type: ignore[union-attr]
                reply_markup=support_order_kb(order)
            )
        except Exception:
            pass
    await callback.answer(
        "⭐ Клиент доверенный — видео перевода не нужно"
        if trusted
        else "Клиент убран из доверенных — снова нужно видео"
    )


@router.callback_query(F.data.startswith("support:video:"))
async def staff_show_video(
    callback: CallbackQuery, settings: Settings, db: Database, bot: Bot
) -> None:
    """Прислать сотруднику в личку видео перевода от клиента."""
    if not settings.is_support(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    order = await db.get_order_by_id(int(callback.data.split(":")[-1]))  # type: ignore[union-attr]
    extra = (order.extra or {}) if order else {}
    file_id = extra.get("payment_video_file_id")
    if order is None or not file_id:
        await callback.answer("Видео нет", show_alert=True)
        return
    kind = extra.get("payment_video_kind") or "video"
    user_id = callback.from_user.id
    caption = f"🎥 Видео перевода {order.public_id}"
    kb = support_order_kb(order)
    try:
        if kind == "video_note":
            await bot.send_video_note(user_id, file_id, reply_markup=kb)
        elif kind == "document":
            await bot.send_document(user_id, file_id, caption=caption, reply_markup=kb)
        else:
            await bot.send_video(user_id, file_id, caption=caption, reply_markup=kb)
    except (TelegramForbiddenError, TelegramBadRequest):
        await callback.answer(
            "Не получилось отправить видео в личку. Откройте чат с ботом, "
            "нажмите /start и повторите.",
            show_alert=True,
        )
        return
    if is_group_callback(callback):
        await open_bot_chat(callback, bot)
    else:
        await callback.answer()


@router.message(Command("trusted"))
async def cmd_trusted(message: Message, settings: Settings, db: Database) -> None:
    """Список доверенных клиентов."""
    if message.from_user is None or not settings.is_support(message.from_user.id):
        return
    items = await db.list_trusted()
    if not items:
        await message.answer(
            "⭐ Доверенных клиентов пока нет.\n"
            "Сделать клиента доверенным: кнопка «⭐ Сделать доверенным» в карточке его заявки."
        )
        return
    lines = [f"⭐ <b>Доверенные клиенты</b> ({len(items)}) — видео перевода не нужно", ""]
    for tg_id, username, added_at in items[:100]:
        name = f"@{escape(username)}" if username else "без юзернейма"
        lines.append(f"• {name} · <code>{tg_id}</code> · с {added_at[:10]}")
    lines.append("")
    lines.append("Убрать: кнопка «Убрать из доверенных» в карточке заявки клиента.")
    await message.answer("\n".join(lines), parse_mode="HTML")


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
