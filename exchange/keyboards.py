from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from exchange.models import Order
from exchange.statuses import OrderStatus


def client_main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Обменять RUB → USDT"), KeyboardButton(text="Меню")],
            [KeyboardButton(text="Мои заявки"), KeyboardButton(text="Курс")],
            [KeyboardButton(text="Помощь")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def client_skip_address_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Указать позже",
                    callback_data="client:skip_address",
                )
            ]
        ]
    )


def client_order_kb(order: Order) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if order.status == OrderStatus.AWAITING_PAYMENT:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Я оплатил",
                    callback_data=f"client:upload:{order.id}",
                )
            ]
        )
    if order.status in {
        OrderStatus.AWAITING_REQUISITES,
        OrderStatus.AWAITING_PAYMENT,
        OrderStatus.RECEIPT_REJECTED,
        OrderStatus.AWAITING_SUPPORT_REVIEW,
        OrderStatus.AWAITING_PAYOUT,
        OrderStatus.DISPUTED,
    } and not order.has_usdt_address:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Указать кошелёк USDT",
                    callback_data=f"wallet:set:{order.id}",
                )
            ]
        )
    if order.status in {
        OrderStatus.AWAITING_REQUISITES,
        OrderStatus.AWAITING_PAYMENT,
        OrderStatus.RECEIPT_REJECTED,
    }:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Отменить заявку",
                    callback_data=f"client:cancel:{order.id}",
                )
            ]
        )
    if order.status == OrderStatus.RECEIPT_REJECTED:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Загрузить другой чек",
                    callback_data=f"client:upload:{order.id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Обновить статус",
                callback_data=f"client:status:{order.id}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def support_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Нужны реквизиты",
                    callback_data="support:queue:need_requisites",
                )
            ],
            [
                InlineKeyboardButton(
                    text="На проверке / reject",
                    callback_data="support:queue:need_review",
                )
            ],
            [
                InlineKeyboardButton(
                    text="В оплате",
                    callback_data="support:queue:in_payment",
                )
            ],
        ]
    )


def support_order_kb(order: Order) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    oid = order.id
    if order.status in {
        OrderStatus.AWAITING_REQUISITES,
        OrderStatus.AWAITING_PAYMENT,
        OrderStatus.RECEIPT_REJECTED,
        OrderStatus.AWAITING_SUPPORT_REVIEW,
        OrderStatus.DISPUTED,
    }:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Изменить курс",
                    callback_data=f"support:rate:{oid}",
                )
            ]
        )
    if order.status == OrderStatus.AWAITING_REQUISITES:
        margin_ok = (order.extra or {}).get("margin_ok")
        take_label = "Взять · выдать реквизиты"
        if margin_ok is False:
            take_label = "Взять всё равно · реквизиты"
        rows.append(
            [
                InlineKeyboardButton(
                    text=take_label,
                    callback_data=f"support:req:{oid}",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Отклонить по марже",
                    callback_data=f"support:reject_margin:{oid}",
                )
            ]
        )
    if order.status not in {OrderStatus.COMPLETED, OrderStatus.CANCELLED}:
        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        "Указать кошелёк USDT"
                        if not order.has_usdt_address
                        else "Сменить кошелёк USDT"
                    ),
                    callback_data=f"wallet:set:{oid}",
                )
            ]
        )
    if order.status in {
        OrderStatus.AWAITING_SUPPORT_REVIEW,
        OrderStatus.RECEIPT_REJECTED,
    }:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Одобрить → админу",
                    callback_data=f"support:approve:{oid}",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Отклонить чек",
                    callback_data=f"support:reject:{oid}",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Попросить оплату заново",
                    callback_data=f"support:repay:{oid}",
                )
            ]
        )
    if order.receipt_file_id:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Показать чек",
                    callback_data=f"support:receipt:{oid}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Спор",
                callback_data=f"support:dispute:{oid}",
            ),
            InlineKeyboardButton(
                text="Отменить",
                callback_data=f"support:cancel:{oid}",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="К выплате USDT",
                    callback_data="admin:queue:need_payout",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Споры",
                    callback_data="admin:queue:disputed",
                )
            ],
        ]
    )


def admin_order_kb(order: Order) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if order.status not in {OrderStatus.COMPLETED, OrderStatus.CANCELLED}:
        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        "Указать кошелёк USDT"
                        if not order.has_usdt_address
                        else "Сменить кошелёк USDT"
                    ),
                    callback_data=f"wallet:set:{order.id}",
                )
            ]
        )
    if order.status == OrderStatus.AWAITING_PAYOUT:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Я выплатил USDT",
                    callback_data=f"admin:payout:{order.id}",
                )
            ]
        )
    if order.receipt_file_id:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Показать чек",
                    callback_data=f"admin:receipt:{order.id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Спор",
                callback_data=f"admin:dispute:{order.id}",
            ),
            InlineKeyboardButton(
                text="Отменить",
                callback_data=f"admin:cancel:{order.id}",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
