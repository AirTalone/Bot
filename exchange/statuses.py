"""Точные статусы заявки и допустимые переходы."""

from __future__ import annotations

from enum import Enum


class OrderStatus(str, Enum):
    """Жизненный цикл заявки на обмен RUB → USDT."""

    # Клиент создал заявку (сумма + адрес USDT). Ждём реквизиты от саппорта.
    AWAITING_REQUISITES = "awaiting_requisites"

    # Саппорт выдал реквизиты с площадки выплат. Ждём оплату и чек от клиента.
    AWAITING_PAYMENT = "awaiting_payment"

    # Клиент загрузил чек. Идёт автоматическая проверка (Fraudex / провайдер).
    CHECKING_RECEIPT = "checking_receipt"

    # Автопроверка не прошла. Клиент может загрузить другой чек; саппорт может
    # всё равно взять в ручной разбор или отклонить.
    RECEIPT_REJECTED = "receipt_rejected"

    # Автопроверка прошла (или саппорт забрал в ручной разбор). Ждём одобрение саппорта.
    AWAITING_SUPPORT_REVIEW = "awaiting_support_review"

    # Саппорт подтвердил оплату. Ждём, пока админ отправит USDT.
    AWAITING_PAYOUT = "awaiting_payout"

    # Админ отметил выплату (есть txid / подтверждение).
    COMPLETED = "completed"

    # Заявка отменена клиентом, саппортом или админом.
    CANCELLED = "cancelled"

    # Истёк таймер оплаты после выдачи реквизитов.
    EXPIRED = "expired"

    # Спор: клиент/саппорт эскалировали, нужна ручная разборка админом.
    DISPUTED = "disputed"


STATUS_LABELS_RU: dict[OrderStatus, str] = {
    OrderStatus.AWAITING_REQUISITES: "Ожидает реквизиты",
    OrderStatus.AWAITING_PAYMENT: "Ожидает оплату",
    OrderStatus.CHECKING_RECEIPT: "Проверка чека",
    OrderStatus.RECEIPT_REJECTED: "Чек не прошёл проверку",
    OrderStatus.AWAITING_SUPPORT_REVIEW: "На проверке у саппорта",
    OrderStatus.AWAITING_PAYOUT: "Ожидает выплату USDT",
    OrderStatus.COMPLETED: "Завершена",
    OrderStatus.CANCELLED: "Отменена",
    OrderStatus.EXPIRED: "Истекла",
    OrderStatus.DISPUTED: "Спор",
}


# Откуда → куда разрешено переходить сервисному слою.
ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.AWAITING_REQUISITES: frozenset(
        {
            OrderStatus.AWAITING_PAYMENT,
            OrderStatus.CANCELLED,
        }
    ),
    OrderStatus.AWAITING_PAYMENT: frozenset(
        {
            OrderStatus.CHECKING_RECEIPT,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
            OrderStatus.DISPUTED,
        }
    ),
    OrderStatus.CHECKING_RECEIPT: frozenset(
        {
            OrderStatus.AWAITING_SUPPORT_REVIEW,
            OrderStatus.RECEIPT_REJECTED,
            OrderStatus.CANCELLED,
            OrderStatus.DISPUTED,
        }
    ),
    OrderStatus.RECEIPT_REJECTED: frozenset(
        {
            OrderStatus.CHECKING_RECEIPT,  # новый чек
            OrderStatus.AWAITING_SUPPORT_REVIEW,  # саппорт взял вручную
            OrderStatus.CANCELLED,
            OrderStatus.DISPUTED,
        }
    ),
    OrderStatus.AWAITING_SUPPORT_REVIEW: frozenset(
        {
            OrderStatus.AWAITING_PAYOUT,  # саппорт одобрил
            OrderStatus.RECEIPT_REJECTED,  # саппорт отклонил чек
            OrderStatus.AWAITING_PAYMENT,  # попросить оплату заново / новые реквизиты
            OrderStatus.CANCELLED,
            OrderStatus.DISPUTED,
        }
    ),
    OrderStatus.AWAITING_PAYOUT: frozenset(
        {
            OrderStatus.COMPLETED,
            OrderStatus.DISPUTED,
            OrderStatus.CANCELLED,
        }
    ),
    OrderStatus.DISPUTED: frozenset(
        {
            OrderStatus.AWAITING_REQUISITES,
            OrderStatus.AWAITING_PAYMENT,
            OrderStatus.AWAITING_SUPPORT_REVIEW,
            OrderStatus.AWAITING_PAYOUT,
            OrderStatus.COMPLETED,
            OrderStatus.CANCELLED,
        }
    ),
    OrderStatus.COMPLETED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.EXPIRED: frozenset(
        {
            OrderStatus.AWAITING_REQUISITES,  # переоткрыть / новая выдача
            OrderStatus.CANCELLED,
        }
    ),
}


CLIENT_VISIBLE_ACTIVE: frozenset[OrderStatus] = frozenset(
    {
        OrderStatus.AWAITING_REQUISITES,
        OrderStatus.AWAITING_PAYMENT,
        OrderStatus.CHECKING_RECEIPT,
        OrderStatus.RECEIPT_REJECTED,
        OrderStatus.AWAITING_SUPPORT_REVIEW,
        OrderStatus.AWAITING_PAYOUT,
        OrderStatus.DISPUTED,
    }
)


SUPPORT_QUEUES: dict[str, frozenset[OrderStatus]] = {
    "need_requisites": frozenset({OrderStatus.AWAITING_REQUISITES}),
    "need_review": frozenset(
        {
            OrderStatus.AWAITING_SUPPORT_REVIEW,
            OrderStatus.RECEIPT_REJECTED,
        }
    ),
    "in_payment": frozenset(
        {
            OrderStatus.AWAITING_PAYMENT,
            OrderStatus.CHECKING_RECEIPT,
        }
    ),
}


ADMIN_QUEUES: dict[str, frozenset[OrderStatus]] = {
    "need_payout": frozenset({OrderStatus.AWAITING_PAYOUT}),
    "disputed": frozenset({OrderStatus.DISPUTED}),
}


def can_transition(current: OrderStatus, new: OrderStatus) -> bool:
    if current == new:
        return True
    return new in ALLOWED_TRANSITIONS.get(current, frozenset())


def label(status: OrderStatus | str) -> str:
    if isinstance(status, str):
        status = OrderStatus(status)
    return STATUS_LABELS_RU[status]
