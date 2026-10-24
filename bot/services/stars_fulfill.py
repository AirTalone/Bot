"""Apply a verified Telegram Stars payment to an order and optionally provision."""

from __future__ import annotations

import logging

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.keyboards import order_keyboard
from bot.models import Order, OrderStatus
from bot.notifications import notify_admins
from bot.services.delivery import deliver_access_link
from bot.services.orders import get_order, get_order_by_charge_id, mark_paid
from bot.services.panel import PanelError, build_panel_client
from bot.services.provisioning import provision_and_fulfill
from bot.services.stars import decode_stars_payload, validate_stars_payment
from bot.texts import admin_order_text, stars_paid_pending_text

logger = logging.getLogger(__name__)


async def apply_stars_payment(
    session: AsyncSession,
    bot: Bot,
    settings: Settings,
    *,
    user_id: int,
    currency: str,
    total_amount: int,
    invoice_payload: str,
    telegram_payment_charge_id: str,
) -> Order | None:
    """
    Idempotent Stars success handler.

    Returns the order after processing, or None if payload is invalid.
    Replay with the same charge_id is a no-op that returns the existing order.
    """
    existing = await get_order_by_charge_id(session, telegram_payment_charge_id)
    if existing is not None:
        return existing

    parsed = decode_stars_payload(invoice_payload)
    if parsed is None:
        logger.warning("stars payment with bad payload: %s", invoice_payload)
        return None

    order = await get_order(session, parsed.order_id)
    if order is None:
        logger.warning("stars payment for missing order %s", parsed.order_id)
        return None

    expected = int(order.stars_amount or 0)
    error = validate_stars_payment(
        currency=currency,
        total_amount=total_amount,
        expected_amount=expected,
        order_status=order.status,
        order_payment_code=order.payment_code,
        payload_code=parsed.payment_code,
    )
    if error is not None:
        # Already paid path: if status moved on, treat as replay only when charge matches later.
        if order.status != OrderStatus.awaiting_payment.value:
            logger.info("stars payment ignored for order %s: %s", order.id, error)
            return order
        logger.warning("stars payment rejected for order %s: %s", order.id, error)
        return None

    claimed = await mark_paid(
        session,
        order.id,
        order.user_id,
        payment_method="stars",
        stars_amount=total_amount,
        telegram_payment_charge_id=telegram_payment_charge_id,
    )
    if claimed is None:
        # Race: another worker claimed first; try charge lookup again.
        return await get_order_by_charge_id(session, telegram_payment_charge_id) or await get_order(
            session, order.id
        )

    if settings.panel_enabled:
        panel = None
        try:
            panel = build_panel_client(settings)
            if panel is None:
                raise PanelError("panel client is not configured")
            fulfilled = await provision_and_fulfill(session, claimed, panel)
        except PanelError as exc:
            logger.warning("stars auto-provision failed for order %s: %s", claimed.id, exc)
            await notify_admins(
                bot,
                settings,
                admin_order_text(claimed, panel_enabled=True)
                + f"\n\nStars оплачены, панель ошиблась: {exc}",
                reply_markup=order_keyboard(claimed.id, panel_enabled=True),
            )
            await bot.send_message(user_id, stars_paid_pending_text(claimed))
            return claimed
        finally:
            if panel is not None:
                await panel.aclose()
        await deliver_access_link(bot, fulfilled)
        return fulfilled

    await notify_admins(
        bot,
        settings,
        admin_order_text(claimed, panel_enabled=False),
        reply_markup=order_keyboard(claimed.id, panel_enabled=False),
    )
    await bot.send_message(user_id, stars_paid_pending_text(claimed))
    return claimed
