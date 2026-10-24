"""Telegram Stars invoice helpers (currency XTR)."""

from __future__ import annotations

from dataclasses import dataclass

STARS_CURRENCY = "XTR"
PAYLOAD_PREFIX = "order:"


@dataclass(frozen=True, slots=True)
class StarsPayload:
    order_id: int
    payment_code: str


def encode_stars_payload(*, order_id: int, payment_code: str) -> str:
    payload = f"{PAYLOAD_PREFIX}{order_id}:{payment_code}"
    if len(payload.encode("utf-8")) > 128:
        raise ValueError("stars invoice payload too long")
    return payload


def decode_stars_payload(raw: str) -> StarsPayload | None:
    text = (raw or "").strip()
    if not text.startswith(PAYLOAD_PREFIX):
        return None
    body = text[len(PAYLOAD_PREFIX) :]
    order_part, sep, code = body.partition(":")
    if not sep or not order_part.isdigit() or not code:
        return None
    return StarsPayload(order_id=int(order_part), payment_code=code)


def validate_stars_payment(
    *,
    currency: str,
    total_amount: int,
    expected_amount: int,
    order_status: str,
    order_payment_code: str,
    payload_code: str,
) -> str | None:
    """Return human-readable error or None if payment is acceptable."""
    if currency != STARS_CURRENCY:
        return "Неверная валюта платежа."
    if total_amount != expected_amount:
        return "Сумма не совпадает с заказом."
    if payload_code != order_payment_code:
        return "Код заказа не совпадает."
    if order_status != "awaiting_payment":
        return "Заказ уже обработан."
    if expected_amount < 1:
        return "Тариф недоступен для оплаты Stars."
    return None
