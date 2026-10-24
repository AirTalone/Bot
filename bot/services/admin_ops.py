"""Operator admin helpers: stats, search, audit, maintenance, CSV, broadcast list."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models import AdminAuditLog, Order, OrderStatus, RuntimeState, User


def utcnow() -> datetime:
    return datetime.now(UTC)


def day_start(now: datetime | None = None) -> datetime:
    current = now or utcnow()
    return current.replace(hour=0, minute=0, second=0, microsecond=0)


@dataclass(frozen=True, slots=True)
class AdminStats:
    awaiting_payment: int
    pending_review: int
    fulfilled_today: int
    active_subs: int
    panel_errors_today: int
    users_total: int
    maintenance: bool


async def ensure_runtime_state(session: AsyncSession) -> RuntimeState:
    state = await session.get(RuntimeState, 1)
    if state is None:
        state = RuntimeState(id=1, maintenance=False)
        session.add(state)
        await session.flush()
    return state


async def is_maintenance(session: AsyncSession) -> bool:
    state = await ensure_runtime_state(session)
    return bool(state.maintenance)


async def set_maintenance(session: AsyncSession, enabled: bool) -> RuntimeState:
    state = await ensure_runtime_state(session)
    state.maintenance = enabled
    await session.flush()
    return state


async def record_audit(
    session: AsyncSession,
    *,
    admin_telegram_id: int,
    action: str,
    detail: str | None = None,
    order_id: int | None = None,
) -> AdminAuditLog:
    entry = AdminAuditLog(
        admin_telegram_id=admin_telegram_id,
        action=action,
        detail=(detail or "")[:2000] or None,
        order_id=order_id,
        created_at=utcnow(),
    )
    session.add(entry)
    await session.flush()
    return entry


async def collect_stats(session: AsyncSession) -> AdminStats:
    start = day_start()
    awaiting = await session.scalar(
        select(func.count()).select_from(Order).where(Order.status == OrderStatus.awaiting_payment.value)
    )
    pending = await session.scalar(
        select(func.count()).select_from(Order).where(Order.status == OrderStatus.pending_review.value)
    )
    fulfilled_today = await session.scalar(
        select(func.count())
        .select_from(Order)
        .where(
            Order.status == OrderStatus.fulfilled.value,
            Order.resolved_at.is_not(None),
            Order.resolved_at >= start,
        )
    )
    now = utcnow()
    active_subs = await session.scalar(
        select(func.count())
        .select_from(Order)
        .where(
            Order.status == OrderStatus.fulfilled.value,
            Order.access_link.is_not(None),
            or_(Order.expires_at.is_(None), Order.expires_at > now),
        )
    )
    panel_errors = await session.scalar(
        select(func.count())
        .select_from(AdminAuditLog)
        .where(AdminAuditLog.action == "panel_error", AdminAuditLog.created_at >= start)
    )
    users_total = await session.scalar(select(func.count()).select_from(User))
    maintenance = await is_maintenance(session)
    return AdminStats(
        awaiting_payment=int(awaiting or 0),
        pending_review=int(pending or 0),
        fulfilled_today=int(fulfilled_today or 0),
        active_subs=int(active_subs or 0),
        panel_errors_today=int(panel_errors or 0),
        users_total=int(users_total or 0),
        maintenance=maintenance,
    )


async def search_orders(session: AsyncSession, query: str, *, limit: int = 10) -> list[Order]:
    text = query.strip()
    if not text:
        return []
    conditions = []
    if text.isdigit():
        telegram_id = int(text)
        conditions.append(User.telegram_id == telegram_id)
        conditions.append(Order.id == telegram_id)
    code = text.upper()
    conditions.append(Order.payment_code == code)
    conditions.append(Order.payment_code == text)
    if text.startswith("@"):
        conditions.append(User.username == text[1:])
    else:
        conditions.append(User.username == text)

    result = await session.scalars(
        select(Order)
        .join(User, Order.user_id == User.id)
        .where(or_(*conditions))
        .options(selectinload(Order.user), selectinload(Order.tariff))
        .order_by(Order.id.desc())
        .limit(limit)
    )
    return list(result)


async def list_broadcast_recipients(session: AsyncSession) -> list[int]:
    result = await session.scalars(select(User.telegram_id).order_by(User.id.asc()))
    return list(result)


async def list_orders_for_export(
    session: AsyncSession,
    *,
    days: int = 30,
    limit: int = 5000,
) -> list[Order]:
    since = utcnow() - timedelta(days=max(1, days))
    result = await session.scalars(
        select(Order)
        .where(Order.created_at >= since)
        .options(selectinload(Order.user))
        .order_by(Order.id.desc())
        .limit(limit)
    )
    return list(result)


def orders_to_csv(orders: list[Order]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "order_id",
            "payment_code",
            "status",
            "tariff",
            "price_minor",
            "duration_days",
            "telegram_id",
            "username",
            "panel_username",
            "expires_at",
            "created_at",
            "claimed_at",
            "resolved_at",
        ]
    )
    for order in orders:
        user = order.user
        writer.writerow(
            [
                order.id,
                order.payment_code,
                order.status,
                order.tariff_title,
                order.price_minor,
                order.duration_days,
                user.telegram_id,
                user.username or "",
                order.panel_username or "",
                order.expires_at.isoformat() if order.expires_at else "",
                order.created_at.isoformat() if order.created_at else "",
                order.claimed_at.isoformat() if order.claimed_at else "",
                order.resolved_at.isoformat() if order.resolved_at else "",
            ]
        )
    return buffer.getvalue()
