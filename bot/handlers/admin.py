import asyncio
import logging
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.callbacks import AdminBroadcastAction, AdminMenuAction, AdminOrderAction, AdminUserAction
from bot.config import Settings
from bot.filters import IsAdmin
from bot.keyboards import (
    admin_home_keyboard,
    broadcast_confirm_keyboard,
    order_keyboard,
    pending_list_keyboard,
    search_results_keyboard,
)
from bot.models import Order, OrderStatus
from bot.services.admin_ops import (
    collect_stats,
    list_broadcast_recipients,
    list_orders_for_export,
    orders_to_csv,
    record_audit,
    search_orders,
    set_maintenance,
)
from bot.services.delivery import deliver_access_link
from bot.services.ops_report import collect_weekly_report
from bot.services.orders import count_orders, fulfill_order, get_order, list_pending, reject_order
from bot.services.panel import PanelError, build_panel_client
from bot.services.payments import is_access_link
from bot.services.provisioning import provision_and_fulfill
from bot.states import AdminBroadcastStates, AdminLinkStates, AdminSearchStates
from bot.texts import (
    admin_home_text,
    admin_order_text,
    ask_broadcast_text,
    ask_link_text,
    ask_search_text,
    ban_done_text,
    broadcast_done_text,
    confirm_broadcast_text,
    link_saved_undelivered_text,
    link_sent_text,
    panel_failed_text,
    pending_list_text,
    rejected_admin_text,
    rejected_text,
    search_results_text,
    weekly_ops_report_text,
)

logger = logging.getLogger(__name__)

router = Router(name="admin")
router.message.filter(F.chat.type == ChatType.PRIVATE, IsAdmin())
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE, IsAdmin())


async def show_home(message: Message, session: AsyncSession, *, edit: bool) -> None:
    stats = await collect_stats(session)
    text = admin_home_text(stats)
    markup = admin_home_keyboard(maintenance=stats.maintenance)
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
    ok = await deliver_access_link(bot, order)
    if ok:
        await admin_message.answer(link_sent_text(order))
    else:
        await admin_message.answer(link_saved_undelivered_text(order))


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


async def show_weekly_report(message: Message, session: AsyncSession, *, edit: bool) -> None:
    report = await collect_weekly_report(session, window_days=7)
    text = weekly_ops_report_text(report)
    markup = admin_home_keyboard(maintenance=(await collect_stats(session)).maintenance)
    if edit:
        try:
            await message.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest:
            logger.debug("failed to edit weekly report", exc_info=True)
    await message.answer(text, reply_markup=markup)


@router.message(Command("admin"))
async def admin_home(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await show_home(message, session, edit=False)


@router.message(Command("report"))
async def admin_report_command(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is not None:
        await record_audit(session, admin_telegram_id=message.from_user.id, action="weekly_report")
    await show_weekly_report(message, session, edit=False)


@router.callback_query(AdminMenuAction.filter(F.action == "home"))
async def admin_home_callback(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    await state.clear()
    await callback.answer()
    await show_home(callback.message, session, edit=True)


@router.callback_query(AdminMenuAction.filter(F.action == "queue"))
async def admin_queue(callback: CallbackQuery, session: AsyncSession) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    await callback.answer()
    await show_queue(callback.message, session, edit=True)


@router.callback_query(AdminMenuAction.filter(F.action == "search"))
async def admin_search_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminSearchStates.waiting_query)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(ask_search_text())


@router.callback_query(AdminMenuAction.filter(F.action == "broadcast"))
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminBroadcastStates.waiting_text)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(ask_broadcast_text())


@router.callback_query(AdminMenuAction.filter(F.action == "report"))
async def admin_report_callback(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    if callback.from_user is None or not isinstance(callback.message, Message):
        await callback.answer()
        return
    await record_audit(session, admin_telegram_id=callback.from_user.id, action="weekly_report")
    await callback.answer()
    await show_weekly_report(callback.message, session, edit=True)


@router.callback_query(AdminMenuAction.filter(F.action == "export"))
async def admin_export(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    if callback.from_user is None or not isinstance(callback.message, Message) or callback.bot is None:
        await callback.answer()
        return
    await callback.answer("Готовлю CSV…")
    orders = await list_orders_for_export(session, days=settings.export_days)
    csv_body = orders_to_csv(orders)
    await record_audit(
        session,
        admin_telegram_id=callback.from_user.id,
        action="export_csv",
        detail=f"days={settings.export_days}; rows={len(orders)}",
    )
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    await callback.message.answer_document(
        BufferedInputFile(csv_body.encode("utf-8"), filename=f"orders_{stamp}.csv"),
        caption=f"Заказы за {settings.export_days} дн.: {len(orders)} строк.",
    )


@router.callback_query(AdminMenuAction.filter(F.action == "maint"))
async def admin_toggle_maintenance(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if callback.from_user is None or not isinstance(callback.message, Message):
        await callback.answer()
        return
    stats = await collect_stats(session)
    new_value = not stats.maintenance
    await set_maintenance(session, new_value)
    await record_audit(
        session,
        admin_telegram_id=callback.from_user.id,
        action="maintenance_on" if new_value else "maintenance_off",
    )
    await state.clear()
    await callback.answer("Техработы включены" if new_value else "Техработы выключены")
    await show_home(callback.message, session, edit=True)


@router.message(AdminSearchStates.waiting_query, Command("cancel"))
@router.message(AdminBroadcastStates.waiting_text, Command("cancel"))
@router.message(AdminBroadcastStates.confirm, Command("cancel"))
async def cancel_admin_flow(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.")
    await show_home(message, session, edit=False)


@router.message(AdminSearchStates.waiting_query, F.text)
async def receive_search_query(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    if message.from_user is None:
        return
    query = (message.text or "").strip()
    if query.startswith("/"):
        await state.clear()
        await message.answer("Поиск отменён.")
        return
    orders = await search_orders(session, query)
    await record_audit(
        session,
        admin_telegram_id=message.from_user.id,
        action="search",
        detail=query[:200],
    )
    await state.clear()
    await message.answer(
        search_results_text(orders),
        reply_markup=search_results_keyboard(orders, panel_enabled=settings.panel_enabled),
    )


@router.message(AdminBroadcastStates.waiting_text, F.text)
async def receive_broadcast_text(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    text = (message.text or "").strip()
    if text.startswith("/"):
        await state.clear()
        await message.answer("Рассылка отменена.")
        return
    if len(text) < 2:
        await message.answer("Слишком короткий текст.")
        return
    recipients = await list_broadcast_recipients(session)
    await state.set_state(AdminBroadcastStates.confirm)
    await state.update_data(broadcast_text=text)
    await message.answer(
        confirm_broadcast_text(text, len(recipients)),
        reply_markup=broadcast_confirm_keyboard(),
    )


@router.callback_query(AdminBroadcastAction.filter(F.action == "cancel"))
async def broadcast_cancel(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Отменено")
    if isinstance(callback.message, Message):
        await show_home(callback.message, session, edit=True)


@router.callback_query(AdminBroadcastAction.filter(F.action == "send"))
async def broadcast_send(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    if callback.from_user is None or callback.bot is None or not isinstance(callback.message, Message):
        await callback.answer()
        return
    data = await state.get_data()
    text = data.get("broadcast_text")
    if not isinstance(text, str) or not text:
        await state.clear()
        await callback.answer("Нет текста рассылки", show_alert=True)
        return
    await state.clear()
    await callback.answer("Рассылка запущена")
    recipients = await list_broadcast_recipients(session)
    await record_audit(
        session,
        admin_telegram_id=callback.from_user.id,
        action="broadcast",
        detail=f"recipients={len(recipients)}; len={len(text)}",
    )
    # Commit audit before long send loop so the session is not held.
    await session.commit()

    sent = 0
    failed = 0
    delay = max(0.0, settings.broadcast_delay_seconds)
    for telegram_id in recipients:
        try:
            await callback.bot.send_message(telegram_id, text)
            sent += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 0.1)
            try:
                await callback.bot.send_message(telegram_id, text)
                sent += 1
            except TelegramAPIError:
                failed += 1
        except TelegramAPIError:
            failed += 1
        if delay:
            await asyncio.sleep(delay)
    await callback.message.answer(broadcast_done_text(sent=sent, failed=failed))


@router.callback_query(AdminUserAction.filter(F.action == "ban"))
async def ban_panel_user(
    callback: CallbackQuery,
    callback_data: AdminUserAction,
    session: AsyncSession,
    settings: Settings,
) -> None:
    if callback.from_user is None:
        await callback.answer()
        return
    order = await get_order(session, callback_data.order_id)
    if order is None or not order.panel_username:
        await callback.answer("Нет panel_username", show_alert=True)
        return
    if not settings.panel_enabled:
        await callback.answer("Панель выключена", show_alert=True)
        return
    panel = None
    try:
        panel = build_panel_client(settings)
        if panel is None:
            raise PanelError("panel client is not configured")
        await panel.disable_user(username=order.panel_username)
    except PanelError as exc:
        logger.warning("panel ban failed for order %s: %s", order.id, exc)
        await record_audit(
            session,
            admin_telegram_id=callback.from_user.id,
            action="panel_error",
            detail=f"ban:{exc}"[:500],
            order_id=order.id,
        )
        await callback.answer("Не удалось отключить в панели", show_alert=True)
        return
    finally:
        if panel is not None:
            await panel.aclose()
    await record_audit(
        session,
        admin_telegram_id=callback.from_user.id,
        action="panel_ban",
        detail=order.panel_username,
        order_id=order.id,
    )
    await callback.answer("Отключён в панели")
    if isinstance(callback.message, Message):
        await callback.message.answer(ban_done_text(order))


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
        if callback.from_user is not None:
            await record_audit(
                session,
                admin_telegram_id=callback.from_user.id,
                action="panel_error",
                detail=str(exc)[:500],
                order_id=order.id,
            )
        await callback.answer("Панель недоступна", show_alert=True)
        if isinstance(callback.message, Message):
            await callback.message.answer(panel_failed_text(order, str(exc)))
        return
    finally:
        if panel is not None:
            await panel.aclose()

    if callback.from_user is not None:
        await record_audit(
            session,
            admin_telegram_id=callback.from_user.id,
            action="fulfill_panel",
            detail=fulfilled.panel_username,
            order_id=fulfilled.id,
        )
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
    if callback.from_user is not None:
        await record_audit(
            session,
            admin_telegram_id=callback.from_user.id,
            action="reject",
            order_id=order.id,
        )
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
@router.message(AdminSearchStates.waiting_query, Command("admin"))
@router.message(AdminBroadcastStates.waiting_text, Command("admin"))
@router.message(AdminBroadcastStates.confirm, Command("admin"))
async def admin_during_input(message: Message, session: AsyncSession, state: FSMContext) -> None:
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
    if message.from_user is not None:
        await record_audit(
            session,
            admin_telegram_id=message.from_user.id,
            action="fulfill_manual",
            order_id=order.id,
        )
    await deliver_access(message.bot, order, message)


@router.message(AdminLinkStates.waiting_link, ~F.text)
async def link_must_be_text(message: Message) -> None:
    await message.answer("Пришлите ссылку обычным текстом.")
