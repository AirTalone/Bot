import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message, User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncSession

from bot.callbacks import CheckoutAction, MenuAction, TariffSelect
from bot.config import Settings
from bot.keyboards import checkout_keyboard, order_keyboard, orders_keyboard, tariffs_keyboard
from bot.models import User
from bot.notifications import notify_admins
from bot.services.orders import (
    cancel_awaiting,
    create_order,
    get_tariff,
    list_active_tariffs,
    list_user_orders,
    mark_paid,
    upsert_user,
)
from bot.services.payments import build_qr_payload, format_money, render_qr_png
from bot.texts import (
    admin_order_text,
    cancelled_text,
    claimed_text,
    orders_text,
    payment_caption,
    tariffs_text,
)
from bot.utils import telegram_full_name

logger = logging.getLogger(__name__)

router = Router(name="user")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)


async def bind_user(tg_user: TelegramUser, session: AsyncSession) -> User:
    return await upsert_user(
        session,
        telegram_id=tg_user.id,
        username=tg_user.username,
        full_name=telegram_full_name(tg_user),
    )


async def show_tariffs(message: Message, session: AsyncSession, settings: Settings, *, edit: bool) -> None:
    tariffs = await list_active_tariffs(session)
    is_admin = message.chat.id in settings.admin_id_list
    text = tariffs_text(tariffs, support_contact=settings.support_contact, is_admin=is_admin)
    markup = tariffs_keyboard(tariffs) if tariffs else None
    if edit:
        try:
            await message.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest:
            logger.debug("failed to edit tariffs message", exc_info=True)
    await message.answer(text, reply_markup=markup)


async def show_orders(
    message: Message,
    tg_user: TelegramUser,
    session: AsyncSession,
    *,
    edit: bool,
) -> None:
    user = await bind_user(tg_user, session)
    orders = await list_user_orders(session, user.id)
    text = orders_text(orders)
    markup = orders_keyboard()
    if edit:
        try:
            await message.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest:
            logger.debug("failed to edit orders message", exc_info=True)
    await message.answer(text, reply_markup=markup)


async def clear_markup(message: Message | None) -> None:
    if message is None:
        return
    try:
        await message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        return


@router.message(CommandStart())
async def start(message: Message, session: AsyncSession, settings: Settings) -> None:
    if message.from_user is None:
        return
    await bind_user(message.from_user, session)
    await show_tariffs(message, session, settings, edit=False)


@router.message(Command("orders"))
async def orders_command(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    await show_orders(message, message.from_user, session, edit=False)


@router.message(Command("admin"))
async def admin_denied(message: Message) -> None:
    await message.answer("Команда доступна только администратору.")


@router.callback_query(MenuAction.filter(F.action == "tariffs"))
async def tariffs_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    await callback.answer()
    await show_tariffs(callback.message, session, settings, edit=True)


@router.callback_query(MenuAction.filter(F.action == "orders"))
async def orders_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or not isinstance(callback.message, Message):
        await callback.answer()
        return
    await callback.answer()
    await show_orders(callback.message, callback.from_user, session, edit=True)


@router.callback_query(TariffSelect.filter())
async def choose_tariff(
    callback: CallbackQuery,
    callback_data: TariffSelect,
    session: AsyncSession,
    settings: Settings,
) -> None:
    if callback.from_user is None or not isinstance(callback.message, Message):
        await callback.answer()
        return
    tariff = await get_tariff(session, callback_data.tariff_id)
    if tariff is None:
        await callback.answer("Тариф недоступен", show_alert=True)
        return
    user = await bind_user(callback.from_user, session)
    order = await create_order(session, user, tariff)
    payload = build_qr_payload(
        payment_title=settings.payment_title,
        payment_details=settings.payment_details,
        static_payload=settings.payment_qr_payload,
        amount=format_money(order.price_minor),
        payment_code=order.payment_code,
    )
    await callback.answer()
    await callback.message.answer_photo(
        BufferedInputFile(render_qr_png(payload), filename=f"{order.payment_code}.png"),
        caption=payment_caption(order, payment_details=settings.payment_details),
        reply_markup=checkout_keyboard(order.id),
    )


@router.callback_query(CheckoutAction.filter(F.action == "paid"))
async def claim_payment(
    callback: CallbackQuery,
    callback_data: CheckoutAction,
    session: AsyncSession,
    settings: Settings,
) -> None:
    if callback.from_user is None or callback.bot is None:
        await callback.answer()
        return
    user = await bind_user(callback.from_user, session)
    order = await mark_paid(session, callback_data.order_id, user.id)
    if order is None:
        await callback.answer("Заявка уже обработана", show_alert=True)
        return
    await callback.answer("Заявка отправлена на проверку")
    if isinstance(callback.message, Message):
        await clear_markup(callback.message)
    delivered = await notify_admins(
        callback.bot,
        settings,
        admin_order_text(order),
        reply_markup=order_keyboard(order.id),
    )
    if delivered == 0:
        logger.warning("order %s claimed but no admin was notified", order.payment_code)
    if isinstance(callback.message, Message):
        await callback.message.answer(claimed_text(order))


@router.callback_query(CheckoutAction.filter(F.action == "cancel"))
async def cancel_payment(
    callback: CallbackQuery,
    callback_data: CheckoutAction,
    session: AsyncSession,
) -> None:
    if callback.from_user is None:
        await callback.answer()
        return
    user = await bind_user(callback.from_user, session)
    order = await cancel_awaiting(session, callback_data.order_id, user.id)
    if order is None:
        await callback.answer("Заявку уже нельзя отменить", show_alert=True)
        return
    await callback.answer("Заявка отменена")
    if isinstance(callback.message, Message):
        await clear_markup(callback.message)
        await callback.message.answer(cancelled_text(order))
