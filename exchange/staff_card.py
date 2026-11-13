"""
Карточка заявки для сотрудников (саппорт / админ): в рабочей группе и в личке.
Стиль — «список со значками»: каждая строка со своим значком, разделители.
"""

from __future__ import annotations

from html import escape
from zoneinfo import ZoneInfo

from exchange.client_card import fmt_rub
from exchange.models import Order
from exchange.statuses import OrderStatus

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
DIVIDER = "━━━━━━━━━━━━━━"

# Значок и короткий заголовок «что сейчас с заявкой / что сделать»
STAFF_VIEW: dict[OrderStatus, tuple[str, str]] = {
    OrderStatus.AWAITING_REQUISITES: ("🆕", "нужны реквизиты"),
    OrderStatus.AWAITING_PAYMENT: ("💳", "ждём оплату"),
    OrderStatus.CHECKING_RECEIPT: ("🔎", "проверяется чек"),
    OrderStatus.RECEIPT_REJECTED: ("⚠️", "чек не прошёл — проверьте"),
    OrderStatus.AWAITING_SUPPORT_REVIEW: ("🧾", "проверьте оплату"),
    OrderStatus.AWAITING_PAYOUT: ("💸", "отправить USDT"),
    OrderStatus.COMPLETED: ("✅", "завершена"),
    OrderStatus.CANCELLED: ("❌", "отменена"),
    OrderStatus.EXPIRED: ("⌛", "истекла"),
    OrderStatus.DISPUTED: ("⚖️", "спор"),
}

CLOSED = frozenset({OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.EXPIRED})


def _num(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _rate_line(order: Order) -> str:
    extra = order.extra or {}
    line = f"📈 Курс: <b>{order.rate:.2f} ₽</b>"
    formula = str(extra.get("quote_formula") or "")
    rapira = _num(extra.get("rapira"))
    cc = _num(extra.get("cryptocards"))
    income = _num(extra.get("income_percent"))
    discount = _num(extra.get("amount_discount_rub")) or 0
    if extra.get("rate_set_by"):
        line += " · изменён вручную"
    elif formula.startswith("cc") and cc is not None:
        line += f" · от CC {cc:.2f}"
        if income is not None:
            line += f", доход {income:g}%"
        if discount:
            line += f", скидка −{discount:g}"
    elif rapira is not None:
        markup = _num(extra.get("markup_rub")) or 0
        # Новая заявка без курса CC — курс взят по запасной формуле
        prefix = "запасной: " if "income_percent" in extra else ""
        line += f" · {prefix}Rapira {rapira:.2f}"
        if markup:
            line += f" + {markup:g}"
        if discount:
            line += f" − {discount:g}"
    return line


def _margin_lines(order: Order) -> list[str]:
    extra = order.extra or {}
    lines = []
    cc = _num(extra.get("cryptocards"))
    cost = _num(extra.get("effective_cost"))
    if cc is not None and cost is not None:
        lines.append(f"🏷 CC {cc:.2f} · себестоимость {cost:.2f}")
    margin = _num(extra.get("margin_percent"))
    min_m = _num(extra.get("min_margin_percent"))
    min_s = f"{min_m:g}%" if min_m is not None else "—"
    ok = extra.get("margin_ok")
    if ok is True and margin is not None:
        lines.append(f"💰 Доход: ✅ {margin:.2f}% (мин. {min_s})")
    elif ok is False and margin is not None:
        lines.append(f"💰 Доход: ⚠️ <b>{margin:.2f}%</b> — ниже мин. {min_s}")
    else:
        lines.append("💰 Доход: ❓ нет курса CC — проверьте курс вручную")
    return lines


def _receipt_line(order: Order) -> str | None:
    status = order.receipt_check_status
    if not status:
        return None
    msg = escape(order.receipt_check_message or "")
    if status == "pending":
        return "🧾 Чек: ⏳ на автопроверке"
    if status == "passed":
        return "🧾 Чек: ✅ автопроверка пройдена"
    return "🧾 Чек: ⚠️ не прошёл" + (f" — {msg}" if msg else "")


def staff_rate_text(rates, settings) -> str:
    """Экран /rate для сотрудников: CC, себестоимость, доход, курс клиенту."""
    snap = rates.snapshot()
    updated = snap.updated_at
    if updated.tzinfo is None:
        from datetime import timezone

        updated = updated.replace(tzinfo=timezone.utc)
    updated_s = updated.astimezone(MOSCOW_TZ).strftime("%H:%M")

    lines = [f"📈 <b>Курс сейчас</b> · обновлено {updated_s} МСК", DIVIDER]
    if snap.cryptocards is not None:
        cost = f" · себестоимость {snap.effective_cost:.2f}" if snap.effective_cost else ""
        lines.append(f"🏷 CC: <b>{snap.cryptocards:.2f}</b>{cost}")
    else:
        lines.append("🏷 CC: ⚠️ нет курса — курс клиенту по Rapira + "
                     f"{settings.markup_rub_default:g}")

    if snap.formula.startswith("cc"):
        lines.append(
            f"💰 Ваш доход: <b>{settings.target_income_percent:g}%</b> "
            f"(макс. {settings.cc_edge_percent:g}%)"
        )
    elif snap.expected_margin_percent is not None:
        lines.append(f"💰 Ваш доход: <b>{snap.expected_margin_percent:.2f}%</b>")

    lines.append(f"👤 Курс клиенту: <b>{snap.client:.2f} ₽</b>")
    # Курс для крупных сумм — каждый порог отдельной строкой
    for tier, discount in (
        (settings.amount_tier_30k, settings.amount_discount_30k),
        (settings.amount_tier_40k, settings.amount_discount_40k),
    ):
        if discount > 0:
            rate = rates.quote_for_amount(tier + 1).suggested_rate
            lines.append(f"     свыше {fmt_rub(tier / 1000)}к → {rate:.2f} ₽")
    if snap.rapira is not None:
        lines.append(f"📊 Rapira: {snap.rapira:.2f} (для справки)")

    lines.append(DIVIDER)
    lines.append(
        f"Лимиты: {fmt_rub(settings.min_amount_rub)}–{fmt_rub(settings.max_amount_rub)} ₽"
    )
    lines.append(
        f"Мин. доход: {settings.min_margin_percent:g}% "
        f"(до {fmt_rub(settings.amount_tier_40k / 1000)}к) · "
        f"{settings.min_margin_percent_40k:g}% (свыше)"
    )
    if snap.errors:
        lines.append("⚠️ " + escape("; ".join(snap.errors)))
    return "\n".join(lines)


def staff_card(
    order: Order, *, owner: tuple[int, str] | None = None, show_owner: bool = False
) -> str:
    """Текст карточки для сотрудников (HTML)."""
    icon, title = STAFF_VIEW.get(order.status, ("•", order.status_label))
    user = (
        f"@{escape(order.client_username)}"
        if order.client_username
        else f"<code>{order.client_tg_id}</code>"
    )
    wallet = (
        f"<code>{escape(order.usdt_address)}</code>"
        if order.has_usdt_address
        else "не указан"
    )

    lines = [
        f"{icon} <b>{order.public_id} — {title}</b>",
        DIVIDER,
        f"👤 Клиент: {user}",
        f"💸 {fmt_rub(order.amount_rub)} ₽ → <b>{order.usdt_exact} USDT</b>",
        _rate_line(order),
        *_margin_lines(order),
        f"👛 Кошелёк: {wallet}",
    ]

    if order.requisites_detail:
        req = [escape(order.requisites_bank or "—"), f"<code>{escape(order.requisites_detail)}</code>"]
        if order.requisites_holder:
            req.append(escape(order.requisites_holder))
        lines.append("🏦 Реквизиты: " + " · ".join(req))
    if order.status == OrderStatus.AWAITING_PAYMENT and order.payment_deadline_at:
        deadline = order.payment_deadline_at.astimezone(MOSCOW_TZ).strftime("%H:%M")
        lines.append(f"⏳ Оплатить до {deadline} МСК")
    receipt = _receipt_line(order)
    if receipt:
        lines.append(receipt)
    if order.payout_txid:
        lines.append(f"🔗 TxID: <code>{escape(order.payout_txid)}</code>")
    if order.cancel_reason and order.status in {OrderStatus.CANCELLED, OrderStatus.EXPIRED}:
        lines.append(f"📝 Причина: {escape(order.cancel_reason)}")
    if order.support_note and order.status == OrderStatus.DISPUTED:
        lines.append(f"📝 Спор: {escape(order.support_note)}")

    if show_owner:
        lines.append(DIVIDER)
        if owner is not None:
            lines.append(f"🙋 Ведёт: {escape(owner[1])}")
        elif order.status not in CLOSED:
            lines.append("🙋 Никто не взял")
        else:
            lines.pop()  # закрытая и никем не взятая — без нижнего разделителя
    return "\n".join(lines)
