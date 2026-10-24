"""Telegram Stars pre-checkout and successful_payment handlers."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.services.orders import get_order
from bot.services.stars import decode_stars_payload, validate_stars_payment
from bot.services.stars_fulfill import apply_stars_payment

logger = logging.getLogger(__name__)

router = Router(name="payments")


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, session: AsyncSession, settings: Settings) -> None:
    if not settings.stars_enabled:
        await query.answer(ok=False, error_message="Оплата Stars временно выключена.")
        return
    parsed = decode_stars_payload(query.invoice_payload)
    if parsed is None:
        await query.answer(ok=False, error_message="Некорректный счёт.")
        return
    order = await get_order(session, parsed.order_id)
    if order is None:
        await query.answer(ok=False, error_message="Заказ не найден.")
        return
    if query.from_user is not None and order.user.telegram_id != query.from_user.id:
        await query.answer(ok=False, error_message="Этот счёт принадлежит другому пользователю.")
        return
    error = validate_stars_payment(
        currency=query.currency,
        total_amount=query.total_amount,
        expected_amount=int(order.stars_amount or 0),
        order_status=order.status,
        order_payment_code=order.payment_code,
        payload_code=parsed.payment_code,
    )
    if error is not None:
        await query.answer(ok=False, error_message=error)
        return
    await query.answer(ok=True)


@router.message(F.chat.type == ChatType.PRIVATE, F.successful_payment)
async def successful_payment(message: Message, session: AsyncSession, settings: Settings) -> None:
    payment = message.successful_payment
    if payment is None or message.from_user is None or message.bot is None:
        return
    if not settings.stars_enabled:
        logger.warning("received successful_payment while STARS_ENABLED=false")
        return
    order = await apply_stars_payment(
        session,
        message.bot,
        settings,
        user_id=message.from_user.id,
        currency=payment.currency,
        total_amount=payment.total_amount,
        invoice_payload=payment.invoice_payload,
        telegram_payment_charge_id=payment.telegram_payment_charge_id,
    )
    if order is None:
        await message.answer("Платёж получен, но заказ не удалось сопоставить. Напишите в поддержку.")
