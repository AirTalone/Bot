"""Модели заявок."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from exchange.statuses import OrderStatus, label


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


@dataclass
class Order:
    id: int
    public_id: str
    client_tg_id: int
    client_username: str | None
    amount_rub: float
    amount_usdt: float
    rate: float
    usdt_address: str
    status: OrderStatus
    created_at: datetime
    updated_at: datetime
    requisites_bank: str | None = None
    requisites_detail: str | None = None
    requisites_holder: str | None = None
    requisites_sbp_url: str | None = None
    requisites_by: int | None = None
    requisites_at: datetime | None = None
    payment_deadline_at: datetime | None = None
    receipt_file_id: str | None = None
    receipt_file_unique_id: str | None = None
    receipt_check_status: str | None = None  # pending | passed | failed | error | skipped
    receipt_check_message: str | None = None
    receipt_check_raw: str | None = None
    support_reviewed_by: int | None = None
    support_reviewed_at: datetime | None = None
    support_note: str | None = None
    payout_txid: str | None = None
    payout_by: int | None = None
    payout_at: datetime | None = None
    cancel_reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def status_label(self) -> str:
        return label(self.status)

    @property
    def usdt_exact(self) -> str:
        """Точная сумма к выплате без лишних нулей (для саппорта/админа)."""
        return f"{self.amount_usdt:.4f}".rstrip("0").rstrip(".")

    @property
    def has_usdt_address(self) -> bool:
        addr = (self.usdt_address or "").strip()
        if len(addr) < 20:
            return False
        return addr.lower() not in {"pending", "не указан", "n/a", "none"}


@dataclass
class Requisites:
    bank: str
    detail: str
    holder: str = ""
    sbp_url: str = ""
