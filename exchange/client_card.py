"""
Карточка заявки для клиента.

Два стиля (переключаются константой CLIENT_CARD_STYLE):
  "minimal" — статус крупно, цифры во врезке, внизу подсказка «что дальше»
  "steps"   — сумма сверху и список этапов, где клиент сейчас

Карточка саппорта/админа — exchange/staff_card.py.
"""

from __future__ import annotations

import re
from html import escape
from zoneinfo import ZoneInfo

from exchange.models import Order
from exchange.rates.pricing import round_usdt_amount
from exchange.statuses import OrderStatus

# Какой стиль показывать клиенту: "minimal" или "steps"
CLIENT_CARD_STYLE = "minimal"

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
NBSP = " "

# Значок и заголовок для каждого статуса
STATUS_VIEW: dict[OrderStatus, tuple[str, str]] = {
    OrderStatus.AWAITING_REQUISITES: ("🕐", "Подбираем реквизиты"),
    OrderStatus.AWAITING_PAYMENT: ("💳", "Ожидаем оплату"),
    OrderStatus.CHECKING_RECEIPT: ("🔎", "Проверяем чек"),
    OrderStatus.RECEIPT_REJECTED: ("⚠️", "Чек не прошёл проверку"),
    OrderStatus.AWAITING_SUPPORT_REVIEW: ("🔎", "Проверяем оплату"),
    OrderStatus.AWAITING_PAYOUT: ("✅", "Оплата подтверждена"),
    OrderStatus.COMPLETED: ("🎉", "Обмен завершён"),
    OrderStatus.CANCELLED: ("❌", "Заявка отменена"),
    OrderStatus.EXPIRED: ("⌛", "Время оплаты истекло"),
    OrderStatus.DISPUTED: ("⚖️", "Заявка на разборе"),
}

# Этапы для стиля "steps": (название, статусы, на которых этот этап — текущий)
STEPS: list[tuple[str, frozenset[OrderStatus]]] = [
    ("Заявка создана", frozenset()),
    ("Подбор реквизитов", frozenset({OrderStatus.AWAITING_REQUISITES})),
    ("Оплата", frozenset({OrderStatus.AWAITING_PAYMENT})),
    (
        "Проверка оплаты",
        frozenset(
            {
                OrderStatus.CHECKING_RECEIPT,
                OrderStatus.RECEIPT_REJECTED,
                OrderStatus.AWAITING_SUPPORT_REVIEW,
            }
        ),
    ),
    ("Отправка USDT", frozenset({OrderStatus.AWAITING_PAYOUT})),
]


def fmt_rub(value: float) -> str:
    """25000 → «25 000», 25000.5 → «25 000.50»."""
    text = f"{value:,.2f}".replace(",", NBSP)
    if text.endswith(".00"):
        text = text[:-3]
    return text


def fmt_rub_plain(value: float) -> str:
    """Сумма для копирования, без пробелов: 25000 / 25000.50."""
    text = f"{value:.2f}"
    return text[:-3] if text.endswith(".00") else text


def fmt_usdt(value: float) -> str:
    """229.3 → «229.3», 229.28 → «229.28», 229.0 → «229»."""
    return f"{round_usdt_amount(value):.2f}".rstrip("0").rstrip(".")


def _clean_reason(reason: str | None) -> str:
    """Убираем служебное «(by 123456)» из причины отмены."""
    if not reason:
        return ""
    return re.sub(r"\s*\(by \d+\)\s*$", "", reason).strip()


def _wallet_line(order: Order) -> str:
    if order.has_usdt_address:
        return f"Кошелёк USDT: <code>{escape(order.usdt_address)}</code>"
    return "Кошелёк USDT: не указан"


def _requisites_block(order: Order) -> str:
    lines = []
    if order.requisites_bank:
        lines.append(f"Банк: <b>{escape(order.requisites_bank)}</b>")
    lines.append(f"Номер: <code>{escape(order.requisites_detail or '')}</code>")
    if order.requisites_holder:
        lines.append(f"Получатель: {escape(order.requisites_holder)}")
    lines.append(f"Сумма: <code>{fmt_rub_plain(order.amount_rub)}</code> ₽")
    text = "<b>Реквизиты для оплаты</b>\n<blockquote>" + "\n".join(lines) + "</blockquote>"
    if order.payment_deadline_at:
        deadline = order.payment_deadline_at.astimezone(MOSCOW_TZ).strftime("%H:%M")
        text += f"\n⏳ Оплатите до <b>{deadline}</b> (МСК)"
    return text


def _next_step_hint(order: Order) -> str:
    """Что клиенту делать дальше — короткая подсказка под карточкой."""
    status = order.status
    if status == OrderStatus.AWAITING_REQUISITES:
        return "Пришлём реквизиты для оплаты сюда — обычно это несколько минут."
    if status == OrderStatus.AWAITING_PAYMENT:
        if (order.extra or {}).get("video_required", True) is False:
            # Доверенный клиент — без видео
            return (
                "Переведите точную сумму по реквизитам, затем нажмите "
                "«Я оплатил» и пришлите чек в формате PDF."
            )
        return (
            "🎥 Пожалуйста, перед переводом включите запись экрана и снимите "
            "весь перевод: от входа в приложение банка до экрана успешной "
            "оплаты. Это помогает нам быстрее подтвердить оплату.\n\n"
            "Переведите точную сумму по реквизитам, затем нажмите «Я оплатил» "
            "и пришлите чек в формате PDF и это видео."
        )
    if status == OrderStatus.CHECKING_RECEIPT:
        return "Чек получен, проверяем его. Это недолго."
    if status == OrderStatus.RECEIPT_REJECTED:
        reason = escape(order.receipt_check_message or "")
        text = f"Причина: {reason}\n" if reason else ""
        return text + "Пришлите другой чек кнопкой ниже или дождитесь ответа поддержки."
    if status == OrderStatus.AWAITING_SUPPORT_REVIEW:
        return "Оператор подтверждает поступление оплаты. Осталось совсем немного."
    if status == OrderStatus.AWAITING_PAYOUT:
        if not order.has_usdt_address:
            return (
                "Укажите кошелёк USDT кнопкой ниже — "
                "без него мы не сможем отправить перевод."
            )
        return "Отправляем USDT на ваш кошелёк. Пришлём хеш перевода, как только он уйдёт."
    if status == OrderStatus.COMPLETED:
        txid = escape(order.payout_txid or "")
        text = f"Хеш перевода: <code>{txid}</code>\n" if txid else ""
        return text + "Спасибо за обмен!"
    if status == OrderStatus.CANCELLED:
        reason = escape(_clean_reason(order.cancel_reason))
        text = f"Причина: {reason}\n" if reason else ""
        return text + "Если обмен ещё нужен — создайте новую заявку."
    if status == OrderStatus.EXPIRED:
        return "Создайте новую заявку, если обмен ещё актуален."
    if status == OrderStatus.DISPUTED:
        return "Поддержка разбирается в ситуации и напишет вам здесь."
    return ""


def _show_wallet(order: Order) -> bool:
    # В закрытых заявках без адреса строку «не указан» не показываем
    if order.status in {OrderStatus.CANCELLED, OrderStatus.EXPIRED}:
        return order.has_usdt_address
    return True


def _card_minimal(order: Order) -> str:
    icon, title = STATUS_VIEW[order.status]
    parts = [
        f"{icon} <b>{title}</b>\nЗаявка {order.public_id}",
        "<blockquote>"
        f"Отдаёте: <b>{fmt_rub(order.amount_rub)} ₽</b>\n"
        f"Получаете: <b>{fmt_usdt(order.amount_usdt)} USDT</b>\n"
        f"Курс: {order.rate:.2f} ₽ за 1 USDT"
        "</blockquote>",
    ]
    if _show_wallet(order):
        parts.append(_wallet_line(order))
    if order.status == OrderStatus.AWAITING_PAYMENT and order.requisites_detail:
        parts.append(_requisites_block(order))
    hint = _next_step_hint(order)
    if hint:
        parts.append(hint)
    return "\n\n".join(parts)


def _steps_list(order: Order) -> str:
    current = next(
        (i for i, (_, statuses) in enumerate(STEPS) if order.status in statuses),
        None,
    )
    if order.status == OrderStatus.COMPLETED:
        current = len(STEPS)  # все этапы пройдены
    lines = []
    for i, (name, _) in enumerate(STEPS):
        if current is not None and i < current:
            lines.append(f"✅ {name}")
        elif i == current:
            mark = "⚠️" if order.status == OrderStatus.RECEIPT_REJECTED else "🔄"
            lines.append(f"{mark} <b>{name}</b>")
        else:
            lines.append(f"▫️ {name}")
    if order.status == OrderStatus.COMPLETED:
        lines.append("🎉 <b>Обмен завершён</b>")
    return "\n".join(lines)


def _card_steps(order: Order) -> str:
    parts = [
        f"<b>Заявка {order.public_id}</b>",
        f"<b>{fmt_rub(order.amount_rub)} ₽ → {fmt_usdt(order.amount_usdt)} USDT</b>\n"
        f"по курсу {order.rate:.2f} ₽",
    ]
    if order.status in {
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED,
        OrderStatus.DISPUTED,
    }:
        icon, title = STATUS_VIEW[order.status]
        parts.append(f"{icon} <b>{title}</b>")
    else:
        parts.append(_steps_list(order))
    if order.status == OrderStatus.AWAITING_PAYMENT and order.requisites_detail:
        parts.append(_requisites_block(order))
    hint = _next_step_hint(order)
    bottom = []
    if hint:
        bottom.append(f"👉 {hint}")
    if _show_wallet(order):
        bottom.append("👛 " + _wallet_line(order))
    if bottom:
        parts.append("\n".join(bottom))
    return "\n\n".join(parts)


def client_card(order: Order, *, style: str | None = None) -> str:
    """Текст заявки для клиента (HTML)."""
    style = style or CLIENT_CARD_STYLE
    if style == "steps":
        return _card_steps(order)
    return _card_minimal(order)
