"""Статистика для сотрудников (/stats): заявки, оборот, маржа, кто сколько провёл."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from exchange.client_card import fmt_rub
from exchange.db import Database
from exchange.models import Order
from exchange.statuses import OrderStatus

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

CLOSED_BAD = frozenset({OrderStatus.CANCELLED, OrderStatus.EXPIRED})


@dataclass
class PeriodStats:
    title: str
    total: int = 0
    completed: int = 0
    cancelled: int = 0
    in_work: int = 0
    turnover_rub: float = 0.0
    turnover_usdt: float = 0.0
    profit_rub: float = 0.0
    profit_known: int = 0  # по скольким завершённым известна себестоимость
    margins: list[float] = field(default_factory=list)
    by_staff: dict[str, int] = field(default_factory=dict)

    @property
    def avg_margin(self) -> float | None:
        return sum(self.margins) / len(self.margins) if self.margins else None


def _float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def compute_period(
    title: str, orders: list[Order], owners: dict[int, tuple[int, str]]
) -> PeriodStats:
    st = PeriodStats(title=title)
    for order in orders:
        st.total += 1
        if order.status in CLOSED_BAD:
            st.cancelled += 1
            continue
        if order.status != OrderStatus.COMPLETED:
            st.in_work += 1
            continue
        st.completed += 1
        st.turnover_rub += order.amount_rub
        st.turnover_usdt += order.amount_usdt
        extra = order.extra or {}
        margin = _float(extra.get("margin_percent"))
        if margin is not None:
            st.margins.append(margin)
        cost = _float(extra.get("effective_cost"))
        if cost:
            st.profit_rub += order.amount_rub - order.amount_usdt * cost
            st.profit_known += 1
        owner = owners.get(order.id)
        name = owner[1] if owner else (
            str(order.requisites_by) if order.requisites_by else "—"
        )
        st.by_staff[name] = st.by_staff.get(name, 0) + 1
    return st


def format_period(st: PeriodStats) -> str:
    lines = [f"<b>{st.title}</b>"]
    body = [
        f"Заявок: <b>{st.total}</b> · завершено {st.completed} · "
        f"в работе {st.in_work} · отменено/истекло {st.cancelled}",
        f"Оборот: <b>{fmt_rub(st.turnover_rub)} ₽</b> → "
        f"<b>{st.turnover_usdt:.2f} USDT</b>",
    ]
    if st.profit_known:
        note = "" if st.profit_known == st.completed else f" (по {st.profit_known} из {st.completed})"
        body.append(f"≈ Прибыль: <b>{fmt_rub(round(st.profit_rub))} ₽</b>{note}")
    if st.avg_margin is not None:
        body.append(f"Средняя маржа: <b>{st.avg_margin:.2f}%</b>")
    if st.by_staff:
        staff = ", ".join(
            f"{escape(name)} — {count}"
            for name, count in sorted(st.by_staff.items(), key=lambda x: -x[1])
        )
        body.append(f"Провели: {staff}")
    lines.append("<blockquote>" + "\n".join(body) + "</blockquote>")
    return "\n".join(lines)


async def build_stats_text(db: Database, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    today_start = now.astimezone(MOSCOW_TZ).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    periods = [
        ("Сегодня", today_start),
        ("7 дней", today_start - timedelta(days=6)),
        ("30 дней", today_start - timedelta(days=29)),
    ]
    oldest = periods[-1][1]
    orders = await db.list_orders_since(oldest)
    owners = await db.owners_for(o.id for o in orders)

    blocks = ["📊 <b>Статистика</b>"]
    for title, since in periods:
        since_utc = since.astimezone(timezone.utc)
        subset = [o for o in orders if o.created_at >= since_utc]
        blocks.append(format_period(compute_period(title, subset, owners)))
    blocks.append(
        "<i>Оборот и прибыль — по завершённым заявкам. Прибыль ≈ рубли клиента "
        "минус выданные USDT по себестоимости (курс CC ÷ 1.02).</i>"
    )
    return "\n\n".join(blocks)
