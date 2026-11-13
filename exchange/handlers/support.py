from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from exchange.client_card import client_card
from exchange.config import Settings
from exchange.staff_card import staff_card
from exchange.db import Database
from exchange.keyboards import client_order_kb, support_home_kb, support_order_kb
from exchange.models import Order, Requisites
from exchange.services import OrderError, OrderService
from exchange.staff_panel import (
    StaffPanel,
    is_group_callback,
    send_receipt,
    start_staff_input,
)
from exchange.states import SupportAssignRequisites, SupportNote, SupportSetRate
from exchange.statuses import SUPPORT_QUEUES

logger = logging.getLogger(__name__)
router = Router(name="support")


def _require_support(settings: Settings, user_id: int) -> bool:
    return settings.is_support(user_id)


async def _load_for_action(
    callback: CallbackQuery, settings: Settings, db: Database, panel: StaffPanel
) -> Order | None:
    """Проверить доступ, найти заявку и закрепить её за сотрудником."""
    if not _require_support(settings, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return None
    order_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    order = await db.get_order_by_id(order_id)
    if order is None:
        await callback.answer("Не найдено", show_alert=True)
        return None
    error = await panel.ensure_owner(order, callback.from_user)
    if error:
        await callback.answer(error, show_alert=True)
        return None
    return order


async def _notify_client(bot: Bot, order: Order, header: str = "") -> None:
    try:
        await bot.send_message(
            order.client_tg_id,
            header + client_card(order),
            parse_mode="HTML",
            reply_markup=client_order_kb(order),
        )
    except Exception:
        logger.exception("client notify failed for %s", order.public_id)


@router.message(Command("support"))
async def support_home(message: Message, settings: Settings) -> None:
    if message.from_user is None or not _require_support(settings, message.from_user.id):
        await message.answer("Нет доступа. Добавьте ваш Telegram ID в SUPPORT_IDS / ADMIN_IDS.")
        return
    await message.answer(
        "Панель саппорта. Выберите очередь:",
        reply_markup=support_home_kb(),
    )


@router.callback_query(F.data.startswith("support:queue:"))
async def support_queue(
    callback: CallbackQuery, settings: Settings, db: Database
) -> None:
    if not _require_support(settings, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    key = callback.data.split(":")[-1]  # type: ignore[union-attr]
    statuses = SUPPORT_QUEUES.get(key)
    if not statuses:
        await callback.answer("Неизвестная очередь", show_alert=True)
        return
    items = await db.list_by_statuses(statuses, limit=15)
    if not items:
        await callback.message.answer("Очередь пуста.")  # type: ignore[union-attr]
        await callback.answer()
        return
    await callback.message.answer(f"Очередь «{key}»: {len(items)}")  # type: ignore[union-attr]
    for order in items:
        await callback.message.answer(  # type: ignore[union-attr]
            staff_card(order),
            parse_mode="HTML",
            reply_markup=support_order_kb(order),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("support:rate:"))
async def support_rate_start(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    db: Database,
    panel: StaffPanel,
    bot: Bot,
) -> None:
    order = await _load_for_action(callback, settings, db, panel)
    if order is None:
        return
    await start_staff_input(
        callback,
        state,
        bot,
        new_state=SupportSetRate.waiting,
        data={"rate_order_id": order.id},
        text=staff_card(order)
        + "\n\nВведите итоговый курс числом (например <code>80.8</code>):",
    )


@router.message(SupportSetRate.waiting)
async def support_rate_finish(
    message: Message,
    state: FSMContext,
    settings: Settings,
    orders: OrderService,
    db: Database,
    bot: Bot,
) -> None:
    if message.from_user is None or not _require_support(settings, message.from_user.id):
        await state.clear()
        return
    raw = (message.text or "").strip().replace(",", ".")
    try:
        rate = float(raw)
    except ValueError:
        await message.answer("Нужно число, например 80.8")
        return
    data = await state.get_data()
    order = await db.get_order_by_id(int(data["rate_order_id"]))
    if order is None:
        await state.clear()
        await message.answer("Заявка исчезла.")
        return
    try:
        order = await orders.set_client_rate(
            order, rate=rate, support_tg_id=message.from_user.id
        )
    except OrderError as exc:
        await message.answer(str(exc))
        await state.clear()
        return
    await state.clear()
    await message.answer(
        "Курс обновлён.\n\n" + staff_card(order),
        parse_mode="HTML",
        reply_markup=support_order_kb(order),
    )
    await _notify_client(bot, order, "📈 <b>Курс по заявке обновлён</b>\n\n")


@router.callback_query(F.data.startswith("support:reject_margin:"))
async def support_reject_margin(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    db: Database,
    panel: StaffPanel,
    bot: Bot,
) -> None:
    order = await _load_for_action(callback, settings, db, panel)
    if order is None:
        return
    await start_staff_input(
        callback,
        state,
        bot,
        new_state=SupportNote.waiting,
        data={"note_order_id": order.id, "note_action": "cancel"},
        text=staff_card(order)
        + "\n\nОтклонение по марже. Укажите причину для клиента "
        "(или «слабая маржа»):",
    )


@router.callback_query(F.data.startswith("support:req:"))
async def support_req_start(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    db: Database,
    panel: StaffPanel,
    bot: Bot,
) -> None:
    order = await _load_for_action(callback, settings, db, panel)
    if order is None:
        return
    warn = ""
    if (order.extra or {}).get("margin_ok") is False:
        warn = (
            "\n\n⚠️ Маржа ниже минимума. Ты всё равно берёшь сделку — "
            "проверь курс перед выдачей реквизитов."
        )
    await start_staff_input(
        callback,
        state,
        bot,
        new_state=SupportAssignRequisites.bank,
        data={"req_order_id": order.id},
        text=staff_card(order)
        + warn
        + f"\n\nВыдача реквизитов для <b>{order.public_id}</b> "
        f"({order.amount_rub:.2f} ₽).\n"
        f"1/3 — название банка (как на площадке):",
    )


@router.message(SupportAssignRequisites.bank)
async def support_req_bank(message: Message, state: FSMContext) -> None:
    await state.update_data(bank=(message.text or "").strip())
    await state.set_state(SupportAssignRequisites.detail)
    await message.answer("2/3 — реквизиты (телефон / карта / счёт):")


@router.message(SupportAssignRequisites.detail)
async def support_req_detail(message: Message, state: FSMContext) -> None:
    await state.update_data(detail=(message.text or "").strip())
    await state.set_state(SupportAssignRequisites.holder)
    await message.answer("3/3 — ФИО / получатель (или «-» если нет):")


@router.message(SupportAssignRequisites.holder)
async def support_req_finish(
    message: Message,
    state: FSMContext,
    orders: OrderService,
    db: Database,
    bot: Bot,
    settings: Settings,
) -> None:
    if message.from_user is None or not _require_support(settings, message.from_user.id):
        await state.clear()
        return

    holder = (message.text or "").strip()
    if holder == "-":
        holder = ""

    data = await state.get_data()
    order = await db.get_order_by_id(int(data["req_order_id"]))
    if order is None:
        await state.clear()
        await message.answer("Заявка исчезла.")
        return

    requisites = Requisites(
        bank=str(data.get("bank") or ""),
        detail=str(data.get("detail") or ""),
        holder=holder,
        sbp_url="",
    )
    try:
        order = await orders.assign_requisites(
            order, support_tg_id=message.from_user.id, requisites=requisites
        )
    except OrderError as exc:
        await message.answer(str(exc))
        await state.clear()
        return

    await state.clear()
    await message.answer(
        "Реквизиты выданы клиенту.\n\n" + staff_card(order),
        parse_mode="HTML",
        reply_markup=support_order_kb(order),
    )
    await _notify_client(bot, order)


@router.callback_query(F.data.startswith("support:approve:"))
async def support_approve(
    callback: CallbackQuery,
    settings: Settings,
    orders: OrderService,
    db: Database,
    bot: Bot,
    panel: StaffPanel,
) -> None:
    order = await _load_for_action(callback, settings, db, panel)
    if order is None:
        return
    try:
        order = await orders.support_approve(
            order, support_tg_id=callback.from_user.id, note="Одобрено саппортом"
        )
    except OrderError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    if not is_group_callback(callback):
        await callback.message.answer(  # type: ignore[union-attr]
            "Одобрено → очередь выплаты админу.\n\n" + staff_card(order),
            parse_mode="HTML",
            reply_markup=support_order_kb(order),
        )
    await _notify_client(bot, order)

    # Без рабочей группы — сообщаем админам в личку
    if not panel.enabled:
        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(
                    admin_id,
                    "💸 Нужна выплата USDT\n\n" + staff_card(order),
                    parse_mode="HTML",
                )
            except Exception:
                logger.exception("admin notify failed")
    await callback.answer("Одобрено → админу на выплату")


@router.callback_query(F.data.startswith("support:reject:"))
async def support_reject_start(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    db: Database,
    panel: StaffPanel,
    bot: Bot,
) -> None:
    order = await _load_for_action(callback, settings, db, panel)
    if order is None:
        return
    await start_staff_input(
        callback,
        state,
        bot,
        new_state=SupportNote.waiting,
        data={"note_order_id": order.id, "note_action": "reject"},
        text=f"Заявка <b>{order.public_id}</b>\nУкажите причину отклонения чека:",
    )


@router.callback_query(F.data.startswith("support:repay:"))
async def support_repay(
    callback: CallbackQuery,
    settings: Settings,
    orders: OrderService,
    db: Database,
    bot: Bot,
    panel: StaffPanel,
) -> None:
    order = await _load_for_action(callback, settings, db, panel)
    if order is None:
        return
    try:
        order = await orders.support_request_new_payment(
            order, support_tg_id=callback.from_user.id
        )
    except OrderError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    if not is_group_callback(callback):
        await callback.message.answer(  # type: ignore[union-attr]
            "Клиенту запрошена повторная оплата/чек.\n\n"
            + staff_card(order),
            parse_mode="HTML",
            reply_markup=support_order_kb(order),
        )
    await _notify_client(bot, order, "🔁 <b>Нужна повторная оплата или новый чек</b>\n\n")
    await callback.answer("Клиенту запрошена повторная оплата")


@router.callback_query(F.data.startswith("support:dispute:"))
@router.callback_query(F.data.startswith("support:cancel:"))
async def support_dispute_or_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    db: Database,
    panel: StaffPanel,
    bot: Bot,
) -> None:
    order = await _load_for_action(callback, settings, db, panel)
    if order is None:
        return
    action = callback.data.split(":")[1]  # type: ignore[union-attr]
    prompt = "Причина спора:" if action == "dispute" else "Причина отмены:"
    await start_staff_input(
        callback,
        state,
        bot,
        new_state=SupportNote.waiting,
        data={"note_order_id": order.id, "note_action": action},
        text=f"Заявка <b>{order.public_id}</b>\n{prompt}",
    )


@router.message(SupportNote.waiting)
async def support_note_finish(
    message: Message,
    state: FSMContext,
    settings: Settings,
    orders: OrderService,
    db: Database,
    bot: Bot,
) -> None:
    if message.from_user is None or not _require_support(settings, message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    order = await db.get_order_by_id(int(data["note_order_id"]))
    if order is None:
        await state.clear()
        await message.answer("Заявка не найдена")
        return
    reason = (message.text or "").strip() or "—"
    action = data["note_action"]
    try:
        if action == "reject":
            order = await orders.support_reject_receipt(
                order, support_tg_id=message.from_user.id, note=reason
            )
        elif action == "dispute":
            order = await orders.mark_disputed(order, reason=reason)
        else:
            order = await orders.cancel(
                order, reason=reason, by_tg_id=message.from_user.id
            )
    except OrderError as exc:
        await message.answer(str(exc))
        await state.clear()
        return

    await state.clear()
    await message.answer(
        staff_card(order),
        parse_mode="HTML",
        reply_markup=support_order_kb(order),
    )
    # Причина (отклонения чека / отмены) уже есть в карточке
    await _notify_client(bot, order)


@router.callback_query(F.data.startswith("support:receipt:"))
async def support_show_receipt(
    callback: CallbackQuery, settings: Settings, db: Database, bot: Bot
) -> None:
    if not _require_support(settings, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    order_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    order = await db.get_order_by_id(order_id)
    if order is None or not order.receipt_file_id:
        await callback.answer("Чека нет", show_alert=True)
        return
    await send_receipt(callback, bot, order, support_order_kb(order))
