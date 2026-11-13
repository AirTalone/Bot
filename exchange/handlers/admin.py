from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from exchange.client_card import client_card
from exchange.config import Settings
from exchange.staff_card import staff_card
from exchange.db import Database
from exchange.keyboards import admin_home_kb, admin_order_kb, client_order_kb
from exchange.services import OrderError, OrderService
from exchange.staff_panel import StaffPanel, send_receipt, start_staff_input
from exchange.states import AdminPayout, SupportNote
from exchange.statuses import ADMIN_QUEUES

logger = logging.getLogger(__name__)
router = Router(name="admin")


def _require_admin(settings: Settings, user_id: int) -> bool:
    return settings.is_admin(user_id)


@router.message(Command("admin"))
async def admin_home(message: Message, settings: Settings) -> None:
    if message.from_user is None or not _require_admin(settings, message.from_user.id):
        await message.answer("Нет доступа. Добавьте ваш Telegram ID в ADMIN_IDS.")
        return
    await message.answer("Панель администратора:", reply_markup=admin_home_kb())


@router.callback_query(F.data.startswith("admin:queue:"))
async def admin_queue(
    callback: CallbackQuery, settings: Settings, db: Database
) -> None:
    if not _require_admin(settings, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    key = callback.data.split(":")[-1]  # type: ignore[union-attr]
    statuses = ADMIN_QUEUES.get(key)
    if not statuses:
        await callback.answer("Неизвестная очередь", show_alert=True)
        return
    items = await db.list_by_statuses(statuses, limit=20)
    if not items:
        await callback.message.answer("Очередь пуста.")  # type: ignore[union-attr]
        await callback.answer()
        return
    for order in items:
        await callback.message.answer(  # type: ignore[union-attr]
            staff_card(order),
            parse_mode="HTML",
            reply_markup=admin_order_kb(order),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:payout:"))
async def admin_payout_start(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    db: Database,
    bot: Bot,
) -> None:
    if not _require_admin(settings, callback.from_user.id):
        await callback.answer("Выплату отмечает только админ", show_alert=True)
        return
    order_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    order = await db.get_order_by_id(order_id)
    if order is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    if not order.has_usdt_address:
        await callback.answer(
            "У заявки ещё нет USDT-адреса. Сначала нажмите «Указать кошелёк USDT».",
            show_alert=True,
        )
        return
    await start_staff_input(
        callback,
        state,
        bot,
        new_state=AdminPayout.waiting_txid,
        data={"payout_order_id": order.id},
        text=f"💸 <b>{order.public_id}</b> · <code>{order.usdt_exact}</code> USDT\n"
        f"Отправьте на <code>{escape(order.usdt_address)}</code>\n"
        f"и пришлите TxID / хеш транзакции:",
    )


@router.message(AdminPayout.waiting_txid)
async def admin_payout_finish(
    message: Message,
    state: FSMContext,
    settings: Settings,
    orders: OrderService,
    db: Database,
    bot: Bot,
    panel: StaffPanel,
) -> None:
    if message.from_user is None or not _require_admin(settings, message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    order = await db.get_order_by_id(int(data["payout_order_id"]))
    if order is None:
        await state.clear()
        await message.answer("Заявка не найдена")
        return
    try:
        order = await orders.admin_complete_payout(
            order, admin_tg_id=message.from_user.id, txid=message.text or ""
        )
    except OrderError as exc:
        await message.answer(str(exc))
        return

    await state.clear()
    done = (
        f"✅ Выплата по <b>{order.public_id}</b> зафиксирована\n"
        f"TxID: <code>{escape(order.payout_txid or '')}</code>"
    )
    if panel.enabled:
        # Карточка в рабочей группе уже обновилась
        await message.answer(done, parse_mode="HTML")
    else:
        await message.answer(
            done + "\n\n" + staff_card(order),
            parse_mode="HTML",
            reply_markup=admin_order_kb(order),
        )
    try:
        await bot.send_message(
            order.client_tg_id,
            client_card(order),
            parse_mode="HTML",
            reply_markup=client_order_kb(order),
        )
    except Exception:
        logger.exception("payout client notify failed")


@router.callback_query(F.data.startswith("admin:receipt:"))
async def admin_show_receipt(
    callback: CallbackQuery, settings: Settings, db: Database, bot: Bot
) -> None:
    if not _require_admin(settings, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    order_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    order = await db.get_order_by_id(order_id)
    if order is None or not order.receipt_file_id:
        await callback.answer("Чека нет", show_alert=True)
        return
    await send_receipt(callback, bot, order, admin_order_kb(order))


@router.callback_query(F.data.startswith("admin:dispute:"))
@router.callback_query(F.data.startswith("admin:cancel:"))
async def admin_dispute_or_cancel(
    callback: CallbackQuery, state: FSMContext, settings: Settings, bot: Bot
) -> None:
    if not _require_admin(settings, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    parts = callback.data.split(":")  # type: ignore[union-attr]
    action, order_id = parts[1], int(parts[2])
    prompt = "Причина спора:" if action == "dispute" else "Причина отмены:"
    await start_staff_input(
        callback,
        state,
        bot,
        new_state=SupportNote.waiting,
        data={"note_order_id": order_id, "note_action": action, "note_as_admin": True},
        text=prompt,
    )
