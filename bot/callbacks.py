from aiogram.filters.callback_data import CallbackData


class TariffSelect(CallbackData, prefix="tariff"):
    tariff_id: int


class CheckoutAction(CallbackData, prefix="checkout"):
    order_id: int
    action: str


class MenuAction(CallbackData, prefix="menu"):
    action: str


class OrderAction(CallbackData, prefix="uorder"):
    order_id: int
    action: str


class AdminMenuAction(CallbackData, prefix="amenu"):
    action: str


class AdminOrderAction(CallbackData, prefix="aorder"):
    order_id: int
    action: str
