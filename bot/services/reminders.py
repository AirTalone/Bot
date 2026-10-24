"""Expiry reminders and expired-subscription notices."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from bot.keyboards import expired_keyboard, reminder_keyboard
from bot.models import Order, OrderStatus
from bot.services.panel.base import PanelClient
from bot.texts import expired_text, reminder_text

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


async def list_due_reminders(
    session: AsyncSession,
    *,
    days_before: int,
    limit: int = 50,
) -> list[Order]:
    now = utcnow()
    window_end = now + timedelta(days=days_before)
    result = await session.scalars(
        select(Order)
        .where(
            Order.status == OrderStatus.fulfilled.value,
            Order.expires_at.is_not(None),
            Order.reminder_sent_at.is_(None),
            Order.expires_at > now,
            Order.expires_at <= window_end,
        )
        .options(selectinload(Order.user))
        .order_by(Order.expires_at.asc())
        .limit(limit)
    )
    return list(result)


async def list_due_expired(
    session: AsyncSession,
    *,
    limit: int = 50,
) -> list[Order]:
    now = utcnow()
    result = await session.scalars(
        select(Order)
        .where(
            Order.status == OrderStatus.fulfilled.value,
            Order.expires_at.is_not(None),
            Order.expired_notified_at.is_(None),
            Order.expires_at <= now,
        )
        .options(selectinload(Order.user))
        .order_by(Order.expires_at.asc())
        .limit(limit)
    )
    return list(result)


async def mark_reminder_sent(session: AsyncSession, order_id: int) -> None:
    await session.execute(
        update(Order)
        .where(Order.id == order_id, Order.reminder_sent_at.is_(None))
        .values(reminder_sent_at=utcnow())
        .execution_options(synchronize_session=False)
    )


async def mark_expired_notified(session: AsyncSession, order_id: int) -> None:
    await session.execute(
        update(Order)
        .where(Order.id == order_id, Order.expired_notified_at.is_(None))
        .values(expired_notified_at=utcnow())
        .execution_options(synchronize_session=False)
    )


async def process_reminders(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    days_before: int,
) -> tuple[int, int]:
    """Send due reminders and expired notices. Returns (reminders, expired)."""
    reminded = 0
    expired = 0
    async with session_factory() as session:
        due = await list_due_reminders(session, days_before=days_before)
        for order in due:
            try:
                await bot.send_message(
                    order.user.telegram_id,
                    reminder_text(order),
                    reply_markup=reminder_keyboard(),
                )
            except TelegramAPIError:
                logger.warning("failed to send reminder for order %s", order.id, exc_info=True)
            await mark_reminder_sent(session, order.id)
            reminded += 1

        due_expired = await list_due_expired(session)
        for order in due_expired:
            try:
                await bot.send_message(
                    order.user.telegram_id,
                    expired_text(order),
                    reply_markup=expired_keyboard(),
                )
            except TelegramAPIError:
                logger.warning("failed to send expired notice for order %s", order.id, exc_info=True)
            await mark_expired_notified(session, order.id)
            expired += 1

        await session.commit()
    return reminded, expired


async def refresh_subscription_link(
    session: AsyncSession,
    *,
    order_id: int,
    user_id: int,
    panel: PanelClient,
) -> Order | None:
    """Re-fetch subscription URL from the panel for the buyer's fulfilled order."""
    order = await session.scalar(
        select(Order)
        .where(
            Order.id == order_id,
            Order.user_id == user_id,
            Order.status == OrderStatus.fulfilled.value,
        )
        .options(selectinload(Order.user))
    )
    if order is None or not order.panel_username:
        return None
    access = await panel.fetch_subscription(username=order.panel_username)
    order.access_link = access.subscription_url
    if access.expires_at is not None:
        order.expires_at = access.expires_at
    await session.flush()
    return order
