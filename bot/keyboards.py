from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.callbacks import (
    AdminMenuAction,
    AdminOrderAction,
    CheckoutAction,
    MenuAction,
    TariffSelect,
)
from bot.models import Order, Tariff
from bot.services.payments import format_money


def tariffs_keyboard(tariffs: list[Tariff]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{tariff.title} · {format_money(tariff.price_minor)}",
                callback_data=TariffSelect(tariff_id=tariff.id).pack(),
            )
        ]
        for tariff in tariffs
    ]
    rows.append([InlineKeyboardButton(text="Мои заказы", callback_data=MenuAction(action="orders").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def orders_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="К тарифам", callback_data=MenuAction(action="tariffs").pack())]
        ]
    )


def checkout_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Я оплатил",
                    callback_data=CheckoutAction(order_id=order_id, action="paid").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отменить",
                    callback_data=CheckoutAction(order_id=order_id, action="cancel").pack(),
                )
            ],
        ]
    )


def admin_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Заявки на проверке",
                    callback_data=AdminMenuAction(action="queue").pack(),
                )
            ]
        ]
    )


def pending_list_keyboard(orders: list[Order]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"Открыть {order.payment_code}",
                callback_data=AdminOrderAction(order_id=order.id, action="open").pack(),
            )
        ]
        for order in orders
    ]
    rows.append(
        [InlineKeyboardButton(text="Обновить", callback_data=AdminMenuAction(action="queue").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_keyboard(order_id: int, *, panel_enabled: bool = False) -> InlineKeyboardMarkup:
    confirm_text = "Подтвердить и выдать из панели" if panel_enabled else "Подтвердить и вставить ссылку"
    rows = [
        [
            InlineKeyboardButton(
                text=confirm_text,
                callback_data=AdminOrderAction(order_id=order_id, action="confirm").pack(),
            )
        ]
    ]
    if panel_enabled:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Вставить ссылку вручную",
                    callback_data=AdminOrderAction(order_id=order_id, action="manual").pack(),
                )
            ]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="Отклонить",
                    callback_data=AdminOrderAction(order_id=order_id, action="reject").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="К списку",
                    callback_data=AdminMenuAction(action="queue").pack(),
                )
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
