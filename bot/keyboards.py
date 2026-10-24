from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.callbacks import (
    AdminBroadcastAction,
    AdminMenuAction,
    AdminOrderAction,
    AdminUserAction,
    CheckoutAction,
    MenuAction,
    OrderAction,
    TariffSelect,
)
from bot.models import Order, OrderStatus, Tariff
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
    rows.append(
        [
            InlineKeyboardButton(text="Мои заказы", callback_data=MenuAction(action="orders").pack()),
            InlineKeyboardButton(text="Инструкция", callback_data=MenuAction(action="help").pack()),
        ]
    )
    rows.append([InlineKeyboardButton(text="FAQ", callback_data=MenuAction(action="faq").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def orders_keyboard(orders: list[Order] | None = None, *, panel_enabled: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for order in orders or []:
        if order.status != OrderStatus.fulfilled:
            continue
        if panel_enabled and order.panel_username and order.access_link:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"Обновить ссылку {order.payment_code}",
                        callback_data=OrderAction(order_id=order.id, action="refresh").pack(),
                    )
                ]
            )
    rows.append(
        [
            InlineKeyboardButton(text="К тарифам", callback_data=MenuAction(action="tariffs").pack()),
            InlineKeyboardButton(text="Продлить", callback_data=MenuAction(action="renew").pack()),
        ]
    )
    rows.append([InlineKeyboardButton(text="Инструкция", callback_data=MenuAction(action="help").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="К тарифам", callback_data=MenuAction(action="tariffs").pack()),
                InlineKeyboardButton(text="FAQ", callback_data=MenuAction(action="faq").pack()),
            ]
        ]
    )


def faq_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="К тарифам", callback_data=MenuAction(action="tariffs").pack()),
                InlineKeyboardButton(text="Инструкция", callback_data=MenuAction(action="help").pack()),
            ]
        ]
    )


def access_granted_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Инструкция", callback_data=MenuAction(action="help").pack()),
                InlineKeyboardButton(text="Мои заказы", callback_data=MenuAction(action="orders").pack()),
            ]
        ]
    )


def reminder_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Продлить", callback_data=MenuAction(action="renew").pack())]
        ]
    )


def expired_keyboard() -> InlineKeyboardMarkup:
    return reminder_keyboard()


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


def admin_home_keyboard(*, maintenance: bool = False) -> InlineKeyboardMarkup:
    maint_label = "Выключить техработы" if maintenance else "Включить техработы"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Заявки на проверке",
                    callback_data=AdminMenuAction(action="queue").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Обновить статистику",
                    callback_data=AdminMenuAction(action="home").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Поиск",
                    callback_data=AdminMenuAction(action="search").pack(),
                ),
                InlineKeyboardButton(
                    text="Рассылка",
                    callback_data=AdminMenuAction(action="broadcast").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Экспорт CSV",
                    callback_data=AdminMenuAction(action="export").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=maint_label,
                    callback_data=AdminMenuAction(action="maint").pack(),
                )
            ],
        ]
    )


def search_results_keyboard(orders: list[Order], *, panel_enabled: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for order in orders:
        if order.status == OrderStatus.pending_review:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"Открыть {order.payment_code}",
                        callback_data=AdminOrderAction(order_id=order.id, action="open").pack(),
                    )
                ]
            )
        if panel_enabled and order.panel_username:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"Отключить в панели {order.payment_code}",
                        callback_data=AdminUserAction(order_id=order.id, action="ban").pack(),
                    )
                ]
            )
    rows.append([InlineKeyboardButton(text="В админку", callback_data=AdminMenuAction(action="home").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отправить",
                    callback_data=AdminBroadcastAction(action="send").pack(),
                ),
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=AdminBroadcastAction(action="cancel").pack(),
                ),
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
        [
            InlineKeyboardButton(text="Обновить", callback_data=AdminMenuAction(action="queue").pack()),
            InlineKeyboardButton(text="В админку", callback_data=AdminMenuAction(action="home").pack()),
        ]
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
