"""Weekly operator metrics (proxy MRR / churn / panel errors)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import AdminAuditLog, Order, OrderStatus, User
from bot.services.payments import format_money


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class WeeklyOpsReport:
    window_days: int
    since: datetime
    until: datetime
    active_subs: int
    new_users: int
    fulfilled_count: int
    revenue_minor: int
    approx_mrr_minor: int
    expired_count: int
    churn_proxy_pct: float
    panel_errors: int
    pending_review: int
    stars_payments: int
    qr_payments: int

    @property
    def revenue_text(self) -> str:
        return format_money(self.revenue_minor)

    @property
    def approx_mrr_text(self) -> str:
        return format_money(self.approx_mrr_minor)


async def collect_weekly_report(session: AsyncSession, *, window_days: int = 7) -> WeeklyOpsReport:
    days = max(1, window_days)
    until = utcnow()
    since = until - timedelta(days=days)
    month_ago = until - timedelta(days=30)

    active_subs = int(
        await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.status == OrderStatus.fulfilled.value,
                Order.access_link.is_not(None),
                or_(Order.expires_at.is_(None), Order.expires_at > until),
            )
        )
        or 0
    )
    new_users = int(
        await session.scalar(
            select(func.count()).select_from(User).where(User.created_at >= since)
        )
        or 0
    )
    fulfilled_count = int(
        await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.status == OrderStatus.fulfilled.value,
                Order.resolved_at.is_not(None),
                Order.resolved_at >= since,
            )
        )
        or 0
    )
    revenue_minor = int(
        await session.scalar(
            select(func.coalesce(func.sum(Order.price_minor), 0)).where(
                Order.status == OrderStatus.fulfilled.value,
                Order.resolved_at.is_not(None),
                Order.resolved_at >= since,
            )
        )
        or 0
    )
    # Proxy MRR: revenue of fulfilled orders in the last 30 days (not GAAP).
    approx_mrr_minor = int(
        await session.scalar(
            select(func.coalesce(func.sum(Order.price_minor), 0)).where(
                Order.status == OrderStatus.fulfilled.value,
                Order.resolved_at.is_not(None),
                Order.resolved_at >= month_ago,
            )
        )
        or 0
    )
    expired_count = int(
        await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.status == OrderStatus.fulfilled.value,
                Order.expires_at.is_not(None),
                Order.expires_at >= since,
                Order.expires_at <= until,
            )
        )
        or 0
    )
    baseline = active_subs + expired_count
    churn_proxy_pct = (100.0 * expired_count / baseline) if baseline else 0.0
    panel_errors = int(
        await session.scalar(
            select(func.count())
            .select_from(AdminAuditLog)
            .where(AdminAuditLog.action == "panel_error", AdminAuditLog.created_at >= since)
        )
        or 0
    )
    pending_review = int(
        await session.scalar(
            select(func.count()).select_from(Order).where(Order.status == OrderStatus.pending_review.value)
        )
        or 0
    )
    stars_payments = int(
        await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.payment_method == "stars",
                Order.status == OrderStatus.fulfilled.value,
                Order.resolved_at.is_not(None),
                Order.resolved_at >= since,
            )
        )
        or 0
    )
    qr_payments = int(
        await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.payment_method == "qr",
                Order.status == OrderStatus.fulfilled.value,
                Order.resolved_at.is_not(None),
                Order.resolved_at >= since,
            )
        )
        or 0
    )
    return WeeklyOpsReport(
        window_days=days,
        since=since,
        until=until,
        active_subs=active_subs,
        new_users=new_users,
        fulfilled_count=fulfilled_count,
        revenue_minor=revenue_minor,
        approx_mrr_minor=approx_mrr_minor,
        expired_count=expired_count,
        churn_proxy_pct=churn_proxy_pct,
        panel_errors=panel_errors,
        pending_review=pending_review,
        stars_payments=stars_payments,
        qr_payments=qr_payments,
    )
