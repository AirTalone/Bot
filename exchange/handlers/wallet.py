"""Указание / смена USDT-адреса на любом этапе до выплаты."""

from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from exchange.client_card import client_card
from exchange.config import Settings
from exchange.staff_card import staff_card
from exchange.db import Database
from exchange.keyboards import admin_order_kb, client_order_kb, support_order_kb
from exchange.services import OrderError, OrderService
from exchange.staff_panel import start_staff_input
from exchange.states import SetUsdtAddress
from exchange.statuses import OrderStatus

logger = logging.getLogger(__name__)
router = Router(name="wallet")


def _can_edit_wallet(
    *, settings: Settings, actor_id: int, client_tg_id: int
) -> bool:
    return (
        actor_id == client_tg_id
        or settings.is_support(actor_id)
        or settings.is_admin(actor_id)
    )


@router.callback_query(F.data.startswith("wallet:set:"))
async def wallet_set_start(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    db: Database,
    bot: Bot,
) -> None:
    order_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    order = await db.get_order_by_id(order_id)
    if order is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if not _can_edit_wallet(
        settings=settings,
        actor_id=callback.from_user.id,
        client_tg_id=order.client_tg_id,
    ):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if order.status in {OrderStatus.COMPLETED, OrderStatus.CANCELLED}:
        await callback.answer("Заявка уже закрыта", show_alert=True)
        return

    current = (
        f"Сейчас: <code>{escape(order.usdt_address)}</code>\n"
        if order.has_usdt_address
        else "Сейчас адрес не указан.\n"
    )
    # Ввод — в личке (если кнопку нажали в рабочей группе, вопрос придёт в личку)
    await start_staff_input(
        callback,
        state,
        bot,
        new_state=SetUsdtAddress.waiting,
        data={"wallet_order_id": order.id},
        text=f"Заявка <b>{order.public_id}</b>\n"
        f"{current}"
        "Пришлите адрес USDT (TRC-20 / как принимаете).\n"
        "/cancel — отменить ввод.",
    )


@router.message(Command("cancel"), StateFilter(SetUsdtAddress))
async def wallet_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Ввод адреса отменён.")


@router.message(SetUsdtAddress.waiting)
async def wallet_set_finish(
    message: Message,
    state: FSMContext,
    settings: Settings,
    orders: OrderService,
    db: Database,
    bot: Bot,
) -> None:
    if message.from_user is None:
        await state.clear()
        return
    data = await state.get_data()
    order = await db.get_order_by_id(int(data["wallet_order_id"]))
    if order is None:
        await state.clear()
        await message.answer("Заявка не найдена.")
        return
    if not _can_edit_wallet(
        settings=settings,
        actor_id=message.from_user.id,
        client_tg_id=order.client_tg_id,
    ):
        await state.clear()
        await message.answer("Нет доступа.")
        return

    try:
        order = await orders.set_usdt_address(
            order, usdt_address=message.text or ""
        )
    except OrderError as exc:
        await message.answer(str(exc))
        return

    await state.clear()

    is_client = message.from_user.id == order.client_tg_id
    if is_client:
        kb = client_order_kb(order)
        text = "👛 <b>Кошелёк сохранён</b>\n\n" + client_card(order)
    else:
        if settings.is_admin(message.from_user.id):
            kb = admin_order_kb(order)
        else:
            kb = support_order_kb(order)
        text = "Адрес USDT сохранён.\n\n" + staff_card(order)

    await message.answer(text, parse_mode="HTML", reply_markup=kb)

    # Если адрес внёс не клиент — уведомим клиента.
    if message.from_user.id != order.client_tg_id:
        try:
            await bot.send_message(
                order.client_tg_id,
                "👛 <b>Кошелёк для заявки указан</b>\n\n" + client_card(order),
                parse_mode="HTML",
                reply_markup=client_order_kb(order),
            )
        except Exception:
            logger.exception("wallet notify client failed")
