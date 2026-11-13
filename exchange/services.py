"""Бизнес-логика заявок и переходов статусов."""

from __future__ import annotations

import functools
import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Awaitable, Callable

from exchange.config import Settings
from exchange.db import Database
from exchange.models import Order, Requisites, iso, utcnow
from exchange.rates import RateService
from exchange.rates.pricing import (
    compute_client_quote,
    reevaluate_margin,
    round_usdt_amount,
)
from exchange.receipt.base import ReceiptCheckResult, ReceiptChecker
from exchange.statuses import OrderStatus, can_transition

logger = logging.getLogger(__name__)


class OrderError(Exception):
    """Ошибка доменной операции."""


OnChange = Callable[[Order], Awaitable[None]]


def _notifies(method):
    """
    После успешной операции сообщить подписчику (панель сотрудников) об изменении.
    Метод может вернуть Order, (Order, …) или список Order.
    """

    @functools.wraps(method)
    async def wrapper(self: "OrderService", *args, **kwargs):
        result = await method(self, *args, **kwargs)
        if isinstance(result, Order):
            changed = [result]
        elif isinstance(result, tuple) and result and isinstance(result[0], Order):
            changed = [result[0]]
        elif isinstance(result, list):
            changed = [o for o in result if isinstance(o, Order)]
        else:
            changed = []
        if self.on_change is not None:
            for order in changed:
                try:
                    await self.on_change(order)
                except Exception:
                    logger.exception("on_change failed for %s", order.public_id)
        return result

    return wrapper


@dataclass
class OrderService:
    db: Database
    settings: Settings
    receipt_checker: ReceiptChecker
    rates: RateService | None = None
    # Вызывается после каждого изменения заявки (обновить карточку в группе)
    on_change: OnChange | None = None

    def _quote_for_amount(self, amount_rub: float):
        if self.rates is not None:
            return self.rates.quote_for_amount(amount_rub)
        return compute_client_quote(
            amount_rub=amount_rub,
            rapira=self.settings.usdt_rate_rub,
            cryptocards=None,
            fallback_rate=self.settings.effective_rate(),
            markup_rub=self.settings.markup_rub_default,
            cc_edge_percent=self.settings.cc_edge_percent,
            tier_30k=self.settings.amount_tier_30k,
            tier_40k=self.settings.amount_tier_40k,
            discount_30k=self.settings.amount_discount_30k,
            discount_40k=self.settings.amount_discount_40k,
            min_margin_percent=self.settings.min_margin_percent,
            min_margin_percent_40k=self.settings.min_margin_percent_40k,
        )

    @_notifies
    async def create_order(
        self,
        *,
        client_tg_id: int,
        client_username: str | None,
        amount_rub: float,
        usdt_address: str,
    ) -> Order:
        if amount_rub < self.settings.min_amount_rub:
            raise OrderError(
                f"Минимальная сумма: {self.settings.min_amount_rub:.0f} ₽"
            )
        if amount_rub > self.settings.max_amount_rub:
            raise OrderError(
                f"Максимальная сумма: {self.settings.max_amount_rub:.0f} ₽"
            )
        address = (usdt_address or "").strip()
        # Адрес необязателен на старте: клиент/саппорт могут указать позже.
        if address and len(address) < 20:
            raise OrderError("Похоже на некорректный USDT-адрес")

        active = await self.db.active_client_order(client_tg_id)
        if active is not None:
            raise OrderError(
                f"У вас уже есть активная заявка {active.public_id} "
                f"({active.status_label}). Дождитесь завершения или отмените её."
            )

        quote = self._quote_for_amount(amount_rub)
        rate = quote.suggested_rate
        amount_usdt = round_usdt_amount(amount_rub / rate)
        return await self.db.create_order(
            client_tg_id=client_tg_id,
            client_username=client_username,
            amount_rub=amount_rub,
            amount_usdt=amount_usdt,
            rate=rate,
            usdt_address=address,
            extra={
                **quote.to_extra(),
                # Доверенным клиентам видео перевода не нужно
                "video_required": not await self.db.is_trusted(client_tg_id),
            },
        )

    @_notifies
    async def set_client_rate(
        self,
        order: Order,
        *,
        rate: float,
        support_tg_id: int,
    ) -> Order:
        """Саппорт ставит итоговый курс до выдачи реквизитов (или пока заявка жива)."""
        if order.status in {OrderStatus.COMPLETED, OrderStatus.CANCELLED}:
            raise OrderError("Нельзя менять курс у закрытой заявки")
        rate = round(rate, 2)
        if rate <= 0:
            raise OrderError("Курс должен быть > 0")

        amount_usdt = round_usdt_amount(order.amount_rub / rate)
        extra = dict(order.extra or {})
        cc = extra.get("cryptocards")
        try:
            cc_f = float(cc) if cc is not None else None
        except (TypeError, ValueError):
            cc_f = None
        cost, margin, min_m, margin_ok = reevaluate_margin(
            client_rate=rate,
            cryptocards=cc_f,
            amount_rub=order.amount_rub,
            cc_edge_percent=self.settings.cc_edge_percent,
            tier_40k=self.settings.amount_tier_40k,
            min_margin_percent=self.settings.min_margin_percent,
            min_margin_percent_40k=self.settings.min_margin_percent_40k,
        )
        extra.update(
            {
                "effective_cost": round(cost, 4) if cost is not None else extra.get(
                    "effective_cost"
                ),
                "margin_percent": round(margin, 4) if margin is not None else None,
                "min_margin_percent": min_m,
                "margin_ok": margin_ok,
                "rate_set_by": support_tg_id,
                "final_rate": rate,
            }
        )
        return await self.db.update_fields(
            order.id,
            rate=rate,
            amount_usdt=amount_usdt,
            extra=extra,
        )

    @_notifies
    async def set_usdt_address(self, order: Order, *, usdt_address: str) -> Order:
        if order.status in {OrderStatus.COMPLETED, OrderStatus.CANCELLED}:
            raise OrderError("Нельзя менять адрес у закрытой заявки")
        address = (usdt_address or "").strip()
        if len(address) < 20:
            raise OrderError("Похоже на некорректный USDT-адрес")
        return await self.db.update_fields(order.id, usdt_address=address)

    async def _transition(self, order: Order, new_status: OrderStatus) -> None:
        if not can_transition(order.status, new_status):
            raise OrderError(
                f"Нельзя перевести {order.public_id} из {order.status.value} "
                f"в {new_status.value}"
            )

    @_notifies
    async def assign_requisites(
        self,
        order: Order,
        *,
        support_tg_id: int,
        requisites: Requisites,
    ) -> Order:
        await self._transition(order, OrderStatus.AWAITING_PAYMENT)
        if not requisites.detail.strip():
            raise OrderError("Нужно указать реквизиты (телефон / карта / счёт)")
        return await self.db.assign_requisites(
            order.id,
            support_tg_id=support_tg_id,
            requisites=requisites,
            ttl_minutes=self.settings.payment_ttl_minutes,
        )

    @_notifies
    async def cancel(
        self,
        order: Order,
        *,
        reason: str,
        by_tg_id: int | None = None,
    ) -> Order:
        if order.status in {
            OrderStatus.COMPLETED,
            OrderStatus.CANCELLED,
        }:
            raise OrderError("Заявка уже закрыта")
        # Из любого незавершённого — в cancelled (через allowed или force для disputed path)
        if not can_transition(order.status, OrderStatus.CANCELLED):
            # completed/cancelled already handled; expired can cancel
            if order.status == OrderStatus.EXPIRED:
                pass
            else:
                raise OrderError("Эту заявку нельзя отменить")
        note = reason
        if by_tg_id is not None:
            note = f"{reason} (by {by_tg_id})"
        return await self.db.update_fields(
            order.id,
            status=OrderStatus.CANCELLED,
            cancel_reason=note,
        )

    @_notifies
    async def mark_disputed(self, order: Order, *, reason: str) -> Order:
        await self._transition(order, OrderStatus.DISPUTED)
        return await self.db.update_fields(
            order.id,
            status=OrderStatus.DISPUTED,
            support_note=reason,
        )

    @_notifies
    async def submit_receipt(
        self,
        order: Order,
        *,
        file_id: str,
        file_unique_id: str,
        file_bytes: bytes,
        filename: str,
        mime_type: str | None,
        video_file_id: str | None = None,
        video_kind: str | None = None,
    ) -> tuple[Order, ReceiptCheckResult]:
        if order.status not in {
            OrderStatus.AWAITING_PAYMENT,
            OrderStatus.RECEIPT_REJECTED,
        }:
            raise OrderError(
                "Чек можно загрузить только когда заявка ждёт оплату "
                "или после отклонения предыдущего чека"
            )

        await self._transition(order, OrderStatus.CHECKING_RECEIPT)
        order = await self.db.update_fields(
            order.id,
            status=OrderStatus.CHECKING_RECEIPT,
            receipt_file_id=file_id,
            receipt_file_unique_id=file_unique_id,
            receipt_check_status="pending",
            receipt_check_message="Отправлено на автопроверку",
            extra={
                **(order.extra or {}),
                # Видео перевода (у доверенных клиентов — нет)
                "payment_video_file_id": video_file_id,
                "payment_video_kind": video_kind,
            },
        )

        result = await self.receipt_checker.check(
            file_bytes=file_bytes,
            filename=filename,
            mime_type=mime_type,
            expected_amount=order.amount_rub,
            user_id=str(order.client_tg_id),
            order_public_id=order.public_id,
        )

        raw_json = json.dumps(result.raw, ensure_ascii=False)[:8000]

        if result.ok:
            order = await self.db.update_fields(
                order.id,
                status=OrderStatus.AWAITING_SUPPORT_REVIEW,
                receipt_check_status=result.status,
                receipt_check_message=result.message,
                receipt_check_raw=raw_json,
            )
        else:
            # Провал автопроверки → receipt_rejected; саппорт всё равно видит в очереди.
            order = await self.db.update_fields(
                order.id,
                status=OrderStatus.RECEIPT_REJECTED,
                receipt_check_status=result.status,
                receipt_check_message=result.message,
                receipt_check_raw=raw_json,
            )
        return order, result

    @_notifies
    async def support_approve(
        self,
        order: Order,
        *,
        support_tg_id: int,
        note: str = "",
    ) -> Order:
        if order.status == OrderStatus.RECEIPT_REJECTED:
            # Ручной override: саппорт забирает отклонённый автопроверкой чек.
            await self._transition(order, OrderStatus.AWAITING_SUPPORT_REVIEW)
            order = await self.db.update_fields(
                order.id,
                status=OrderStatus.AWAITING_SUPPORT_REVIEW,
                support_note=note or "Ручной разбор после reject автопроверки",
            )

        await self._transition(order, OrderStatus.AWAITING_PAYOUT)
        return await self.db.update_fields(
            order.id,
            status=OrderStatus.AWAITING_PAYOUT,
            support_reviewed_by=support_tg_id,
            support_reviewed_at=iso(utcnow()),
            support_note=note or order.support_note,
        )

    @_notifies
    async def support_reject_receipt(
        self,
        order: Order,
        *,
        support_tg_id: int,
        note: str,
    ) -> Order:
        await self._transition(order, OrderStatus.RECEIPT_REJECTED)
        return await self.db.update_fields(
            order.id,
            status=OrderStatus.RECEIPT_REJECTED,
            support_reviewed_by=support_tg_id,
            support_reviewed_at=iso(utcnow()),
            support_note=note,
            receipt_check_status=order.receipt_check_status or "failed",
            receipt_check_message=note,
        )

    @_notifies
    async def support_request_new_payment(
        self,
        order: Order,
        *,
        support_tg_id: int,
        note: str = "",
    ) -> Order:
        """Вернуть на ожидание оплаты (те же или будет перевыдача реквизитов)."""
        await self._transition(order, OrderStatus.AWAITING_PAYMENT)
        # Новый срок оплаты от текущего момента, иначе заявка сразу истечёт
        deadline = utcnow() + timedelta(minutes=self.settings.payment_ttl_minutes)
        return await self.db.update_fields(
            order.id,
            status=OrderStatus.AWAITING_PAYMENT,
            support_reviewed_by=support_tg_id,
            support_reviewed_at=iso(utcnow()),
            support_note=note or "Нужна повторная оплата / новый чек",
            receipt_file_id=None,
            receipt_file_unique_id=None,
            receipt_check_status=None,
            receipt_check_message=None,
            payment_deadline_at=iso(deadline),
        )

    @_notifies
    async def set_client_trusted(
        self, order: Order, *, trusted: bool, by_tg_id: int
    ) -> Order:
        """
        Сделать клиента доверенным (видео перевода не нужно) или убрать из доверенных.
        Флаг video_required обновляется в этой заявке и в активной заявке клиента.
        """
        if trusted:
            await self.db.set_trusted(
                order.client_tg_id, username=order.client_username, added_by=by_tg_id
            )
        else:
            await self.db.remove_trusted(order.client_tg_id)

        async def _apply(target: Order) -> Order:
            extra = dict(target.extra or {})
            extra["video_required"] = not trusted
            return await self.db.update_fields(target.id, extra=extra)

        updated = await _apply(order)
        active = await self.db.active_client_order(order.client_tg_id)
        if active is not None and active.id != order.id:
            active = await _apply(active)
            if self.on_change is not None:
                try:
                    await self.on_change(active)
                except Exception:
                    logger.exception("on_change failed for %s", active.public_id)
        return updated

    @_notifies
    async def extend_payment(self, order: Order, *, support_tg_id: int) -> Order:
        """
        Продлить срок оплаты (клиент говорит с банком):
        срок = выдача реквизитов + PAYMENT_TTL_EXTENDED_MINUTES.
        """
        if order.status != OrderStatus.AWAITING_PAYMENT:
            raise OrderError("Продлить можно только заявку, которая ждёт оплату")
        start = order.requisites_at or utcnow()
        deadline = start + timedelta(minutes=self.settings.payment_ttl_extended_minutes)
        if order.payment_deadline_at and deadline <= order.payment_deadline_at:
            raise OrderError(
                f"Срок уже не меньше {self.settings.payment_ttl_extended_minutes} минут"
            )
        extra = dict(order.extra or {})
        extra.update({"deadline_extended": True, "deadline_extended_by": support_tg_id})
        return await self.db.update_fields(
            order.id, payment_deadline_at=iso(deadline), extra=extra
        )

    @_notifies
    async def admin_complete_payout(
        self,
        order: Order,
        *,
        admin_tg_id: int,
        txid: str,
    ) -> Order:
        if not order.has_usdt_address:
            raise OrderError(
                "Сначала укажите USDT-адрес клиента (кнопка «Указать кошелёк»)"
            )
        await self._transition(order, OrderStatus.COMPLETED)
        txid = txid.strip()
        if len(txid) < 8:
            raise OrderError("Укажите корректный TxID / хеш выплаты")
        return await self.db.update_fields(
            order.id,
            status=OrderStatus.COMPLETED,
            payout_txid=txid,
            payout_by=admin_tg_id,
            payout_at=iso(utcnow()),
        )

    @_notifies
    async def expire_overdue(self) -> list[Order]:
        return await self.db.expire_overdue()
