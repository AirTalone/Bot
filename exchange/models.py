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
    def has_usdt_address(self) -> bool:
        addr = (self.usdt_address or "").strip()
        if len(addr) < 20:
            return False
        return addr.lower() not in {"pending", "не указан", "n/a", "none"}

    def short_card(self, *, for_support: bool = False) -> str:
        user = f"@{self.client_username}" if self.client_username else str(self.client_tg_id)
        address_line = (
            f"Адрес: <code>{self.usdt_address}</code>"
            if self.has_usdt_address
            else "Адрес USDT: <b>не указан</b> (можно позже)"
        )
        lines = [
            f"Заявка <b>{self.public_id}</b>",
            f"Статус: <b>{self.status_label}</b>",
            f"Клиент: {user}",
            f"Сумма: <b>{self.amount_rub:.2f} ₽</b> → <b>{self.amount_usdt:.4f} USDT</b>",
            f"Курс: {self.rate:.4f} ₽/USDT",
            address_line,
        ]
        if for_support:
            quote_block = self.quote_block_html()
            if quote_block:
                lines.append("")
                lines.append(quote_block)
        if self.requisites_detail:
            lines.append("")
            lines.append(f"Банк: {self.requisites_bank or '—'}")
            lines.append(f"Реквизиты: <code>{self.requisites_detail}</code>")
            if self.requisites_holder:
                lines.append(f"Получатель: {self.requisites_holder}")
        if self.receipt_check_status:
            lines.append("")
            lines.append(
                f"Автопроверка чека: <b>{self.receipt_check_status}</b>"
                + (f" — {self.receipt_check_message}" if self.receipt_check_message else "")
            )
        if self.payout_txid:
            lines.append(f"TxID: <code>{self.payout_txid}</code>")
        if self.cancel_reason:
            lines.append(f"Причина: {self.cancel_reason}")
        return "\n".join(lines)

    def quote_block_html(self) -> str:
        """Блок Rapira/CC/маржа для саппорта из extra."""
        extra = self.extra or {}
        if not any(
            key in extra
            for key in ("rapira", "cryptocards", "effective_cost", "margin_percent")
        ):
            return ""
        rapira = extra.get("rapira")
        cc = extra.get("cryptocards")
        cost = extra.get("effective_cost")
        suggested = extra.get("suggested_rate")
        margin = extra.get("margin_percent")
        min_m = extra.get("min_margin_percent")
        margin_ok = extra.get("margin_ok")
        formula = extra.get("quote_formula") or "—"
        discount = extra.get("amount_discount_rub") or 0

        def fmt(value: object) -> str:
            if value is None:
                return "—"
            try:
                return f"{float(value):.4f}"
            except (TypeError, ValueError):
                return str(value)

        if margin_ok is True:
            verdict = "✅ маржа ок"
        elif margin_ok is False:
            verdict = "⚠️ ниже минимума — решение саппорта"
        else:
            verdict = "❓ нет CC — проверь вручную"

        lines = [
            f"Rapira: <b>{fmt(rapira)}</b>",
            f"CryptoCards (закуп): <b>{fmt(cc)}</b>",
            f"Себестоимость (CC − edge): <b>{fmt(cost)}</b>",
        ]
        if discount:
            lines.append(f"Скидка по сумме: <b>−{float(discount):g}</b> ₽ к курсу")
        if suggested is not None:
            lines.append(f"Предложенный курс: <b>{fmt(suggested)}</b> ({formula})")
        lines.append(f"Итоговый курс: <b>{self.rate:.4f}</b>")
        min_s = f"{float(min_m):.2f}%" if min_m is not None else "—"
        margin_s = f"{float(margin):.2f}%" if margin is not None else "—"
        lines.append(f"Маржа: <b>{margin_s}</b> (мин. {min_s}) — {verdict}")
        return "\n".join(lines)


@dataclass
class Requisites:
    bank: str
    detail: str
    holder: str = ""
    sbp_url: str = ""
