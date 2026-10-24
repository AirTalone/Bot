import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.callbacks import AdminMenuAction, AdminOrderAction
from bot.config import Settings
from bot.filters import IsAdmin
from bot.keyboards import admin_home_keyboard, order_keyboard, pending_list_keyboard
from bot.models import Order, OrderStatus
from bot.services.orders import count_orders, fulfill_order, get_order, list_pending, reject_order
from bot.services.panel import PanelError, build_panel_client
from bot.services.payments import is_access_link
from bot.services.provisioning import provision_and_fulfill
from bot.states import AdminLinkStates
from bot.texts import (
    access_granted_text,
    admin_home_text,
    admin_order_text,
    ask_link_text,
    link_saved_undelivered_text,
    link_sent_text,
    panel_failed_text,
    pending_list_text,
    rejected_admin_text,
    rejected_text,
)

logger = logging.getLogger(__name__)

router = Router(name="admin")
router.message.filter(F.chat.type == ChatType.PRIVATE, IsAdmin())
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE, IsAdmin())


async def show_home(message: Message, session: AsyncSession, *, edit: bool) -> None:
    pending = await count_orders(session, OrderStatus.pending_review)
    text = admin_home_text(pending)
    markup = admin_home_keyboard()
    if edit:
        try:
            await message.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest:
            logger.debug("failed to edit admin home", exc_info=True)
    await message.answer(text, reply_markup=markup)


async def show_queue(message: Message, session: AsyncSession, *, edit: bool) -> None:
    orders = await list_pending(session)
    total = await count_orders(session, OrderStatus.pending_review)
    text = pending_list_text(orders, total)
    markup = pending_list_keyboard(orders)
    if edit:
        try:
            await message.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest:
            logger.debug("failed to edit pending queue", exc_info=True)
    await message.answer(text, reply_markup=markup)


async def deliver_access(bot, order: Order, admin_message: Message) -> None:
    try:
        await bot.send_message(order.user.telegram_id, access_granted_text(order))
    except TelegramForbiddenError:
        logger.info("user %s blocked the bot before delivery of order %s", order.user.telegram_id, order.id)
        await admin_message.answer(link_saved_undelivered_text(order))
        return
    except TelegramAPIError:
        logger.exception("failed to deliver access link for order %s", order.id)
        await admin_message.answer(link_saved_undelivered_text(order))
        return
    await admin_message.answer(link_sent_text(order))


async def begin_manual_link(
    callback: CallbackQuery,
    order: Order,
    state: FSMContext,
) -> None:
    await state.set_state(AdminLinkStates.waiting_link)
    await state.update_data(order_id=order.id)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(ask_link_text(order))


@router.message(Command("admin"))
async def admin_home(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await show_home(message, session, edit=False)


@router.callback_query(AdminMenuAction.filter(F.action == "queue"))
async def admin_queue(callback: CallbackQuery, session: AsyncSession) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    await callback.answer()
    await show_queue(callback.message, session, edit=True)


@router.callback_query(AdminOrderAction.filter(F.action == "open"))
async def open_order(
    callback: CallbackQuery,
    callback_data: AdminOrderAction,
    session: AsyncSession,
    settings: Settings,
) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    order = await get_order(session, callback_data.order_id)
    if order is None or order.status != OrderStatus.pending_review:
        await callback.answer("Заявка уже обработана", show_alert=True)
        return
    await callback.answer()
    text = admin_order_text(order, panel_enabled=settings.panel_enabled)
    markup = order_keyboard(order.id, panel_enabled=settings.panel_enabled)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=markup)


@router.callback_query(AdminOrderAction.filter(F.action == "confirm"))
async def confirm_order(
    callback: CallbackQuery,
    callback_data: AdminOrderAction,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    order = await get_order(session, callback_data.order_id)
    if order is None or order.status != OrderStatus.pending_review:
        await callback.answer("Заявка уже обработана", show_alert=True)
        return
    if not settings.panel_enabled:
        await begin_manual_link(callback, order, state)
        return

    panel = None
    try:
        panel = build_panel_client(settings)
        if panel is None:
            raise PanelError("panel client is not configured")
        await callback.answer("Выдаю доступ через панель…")
        fulfilled = await provision_and_fulfill(session, order, panel)
    except PanelError as exc:
        logger.warning("panel provision failed for order %s: %s", order.id, exc)
        await callback.answer("Панель недоступна", show_alert=True)
        if isinstance(callback.message, Message):
            await callback.message.answer(panel_failed_text(order, str(exc)))
        return
    finally:
        if panel is not None:
            await panel.aclose()

    if callback.bot is None or not isinstance(callback.message, Message):
        return
    await deliver_access(callback.bot, fulfilled, callback.message)


@router.callback_query(AdminOrderAction.filter(F.action == "manual"))
async def manual_link(
    callback: CallbackQuery,
    callback_data: AdminOrderAction,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    order = await get_order(session, callback_data.order_id)
    if order is None or order.status != OrderStatus.pending_review:
        await callback.answer("Заявка уже обработана", show_alert=True)
        return
    await begin_manual_link(callback, order, state)


@router.callback_query(AdminOrderAction.filter(F.action == "reject"))
async def reject_payment(
    callback: CallbackQuery,
    callback_data: AdminOrderAction,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    order = await reject_order(session, callback_data.order_id)
    if order is None or callback.bot is None:
        await callback.answer("Заявка уже обработана", show_alert=True)
        return
    data = await state.get_data()
    if data.get("order_id") == order.id:
        await state.clear()
    await callback.answer("Заявка отклонена")
    try:
        await callback.bot.send_message(
            order.user.telegram_id,
            rejected_text(order, support_contact=settings.support_contact),
        )
    except TelegramAPIError:
        logger.exception("failed to notify user about rejected order %s", order.id)
    if isinstance(callback.message, Message):
        await callback.message.answer(rejected_admin_text(order))


@router.message(AdminLinkStates.waiting_link, Command("cancel"))
async def cancel_link_input(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Ввод ссылки отменён. Заявка остаётся на проверке.")


@router.message(AdminLinkStates.waiting_link, Command("admin"))
async def admin_during_link_input(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await show_home(message, session, edit=False)


@router.message(AdminLinkStates.waiting_link, F.text)
async def receive_access_link(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    text = (message.text or "").strip()
    if text.startswith("/"):
        await state.clear()
        await message.answer("Ввод ссылки отменён. Отправьте команду ещё раз.")
        return
    if not is_access_link(text):
        await message.answer("Пришлите только ссылку доступа, без пояснений. В ней должен быть «://».")
        return
    data = await state.get_data()
    order_id = data.get("order_id")
    if not isinstance(order_id, int):
        await state.clear()
        await message.answer("Не нашёл заявку. Откройте её заново через /admin.")
        return
    order = await fulfill_order(session, order_id, text)
    await state.clear()
    if order is None or message.bot is None:
        await message.answer("Заявка уже обработана.")
        return
    await deliver_access(message.bot, order, message)


@router.message(AdminLinkStates.waiting_link, ~F.text)
async def link_must_be_text(message: Message) -> None:
    await message.answer("Пришлите ссылку обычным текстом.")
