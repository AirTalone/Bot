from __future__ import annotations

import logging
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from exchange.client_card import client_card, fmt_rub
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
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


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


def _order_head(order: Order, icon: str, extra: str = "") -> str:
    """Короткая шапка вопроса в личке: номер заявки и сумма."""
    return f"{icon} <b>{order.public_id}</b> · {fmt_rub(order.amount_rub)} ₽{extra}"


async def _done(message: Message, panel: StaffPanel, order: Order, text: str) -> None:
    """
    Итог действия в личке. С рабочей группой — одна строка (карточка в группе
    уже обновилась). Без группы — строка + карточка с кнопками.
    """
    if panel.enabled:
        await message.answer(text, parse_mode="HTML")
    else:
        await message.answer(
            text + "\n\n" + staff_card(order),
            parse_mode="HTML",
            reply_markup=support_order_kb(order),
        )


# Частые банки для кнопок на шаге 1 (любой другой можно написать текстом)
REQ_BANKS = ["Сбер", "Тинькофф", "Альфа", "ВТБ", "Озон", "Яндекс"]


def _req_kb(step: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if step == "bank":
        buttons = [
            InlineKeyboardButton(text=name, callback_data=f"reqbank:{i}")
            for i, name in enumerate(REQ_BANKS)
        ]
        rows += [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    if step == "holder":
        rows.append([InlineKeyboardButton(text="Пропустить", callback_data="reqholder:skip")])
    rows.append([InlineKeyboardButton(text="✖️ Отменить выдачу", callback_data="reqcancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
        text=_order_head(order, "📈", f" · сейчас {order.rate:.2f} ₽")
        + "\nВведите новый курс числом, например <code>87.5</code>",
    )


@router.message(SupportSetRate.waiting)
async def support_rate_finish(
    message: Message,
    state: FSMContext,
    settings: Settings,
    orders: OrderService,
    db: Database,
    bot: Bot,
    panel: StaffPanel,
) -> None:
    if message.from_user is None or not _require_support(settings, message.from_user.id):
        await state.clear()
        return
    raw = (message.text or "").strip().replace(",", ".")
    try:
        rate = float(raw)
    except ValueError:
        await message.answer("Нужно число, например 87.5")
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
    margin = (order.extra or {}).get("margin_percent")
    income = f" · доход {float(margin):.2f}%" if margin is not None else ""
    await _done(
        message, panel, order,
        f"✅ Курс по <b>{order.public_id}</b>: {order.rate:.2f} ₽{income}",
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
        text=_order_head(order, "❌")
        + "\nПричина отклонения для клиента (например «слабая маржа»):",
    )


# ----- Выдача реквизитов: 3 шага (банк → номер → получатель) -----


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
        warn = "\n⚠️ Доход ниже минимума — проверьте курс"
    await start_staff_input(
        callback,
        state,
        bot,
        new_state=SupportAssignRequisites.bank,
        data={"req_order_id": order.id},
        text=_order_head(order, "🏦")
        + warn
        + "\nШаг 1 из 3 — выберите или напишите <b>банк</b>",
        reply_markup=_req_kb("bank"),
    )


async def _ask_detail(answer, state: FSMContext, db: Database, bank: str) -> None:
    data = await state.get_data()
    order = await db.get_order_by_id(int(data["req_order_id"]))
    await state.update_data(bank=bank)
    await state.set_state(SupportAssignRequisites.detail)
    head = _order_head(order, "🏦", f" · {escape(bank)}") if order else "🏦"
    await answer(
        head + "\nШаг 2 из 3 — <b>номер</b> карты / телефона",
        parse_mode="HTML",
        reply_markup=_req_kb("detail"),
    )


@router.callback_query(SupportAssignRequisites.bank, F.data.startswith("reqbank:"))
async def support_req_bank_button(
    callback: CallbackQuery, state: FSMContext, db: Database
) -> None:
    idx = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    await callback.answer()
    await _ask_detail(callback.message.answer, state, db, REQ_BANKS[idx])  # type: ignore[union-attr]


@router.message(SupportAssignRequisites.bank)
async def support_req_bank(message: Message, state: FSMContext, db: Database) -> None:
    bank = (message.text or "").strip()
    if not bank:
        await message.answer("Напишите название банка текстом или выберите кнопкой.")
        return
    await _ask_detail(message.answer, state, db, bank)


@router.message(SupportAssignRequisites.detail)
async def support_req_detail(message: Message, state: FSMContext, db: Database) -> None:
    detail = (message.text or "").strip()
    if not detail:
        await message.answer("Пришлите номер карты или телефона текстом.")
        return
    await state.update_data(detail=detail)
    await state.set_state(SupportAssignRequisites.holder)
    data = await state.get_data()
    order = await db.get_order_by_id(int(data["req_order_id"]))
    bank = str(data.get("bank") or "")
    head = _order_head(order, "🏦", f" · {escape(bank)}") if order else "🏦"
    await message.answer(
        head + "\nШаг 3 из 3 — <b>получатель</b> (ФИО)",
        parse_mode="HTML",
        reply_markup=_req_kb("holder"),
    )


async def _finish_requisites(
    *,
    user_id: int,
    holder: str,
    answer_message: Message,
    state: FSMContext,
    orders: OrderService,
    db: Database,
    bot: Bot,
    panel: StaffPanel,
) -> None:
    data = await state.get_data()
    order = await db.get_order_by_id(int(data["req_order_id"]))
    if order is None:
        await state.clear()
        await answer_message.answer("Заявка исчезла.")
        return
    requisites = Requisites(
        bank=str(data.get("bank") or ""),
        detail=str(data.get("detail") or ""),
        holder=holder,
        sbp_url="",
    )
    try:
        order = await orders.assign_requisites(
            order, support_tg_id=user_id, requisites=requisites
        )
    except OrderError as exc:
        await answer_message.answer(str(exc))
        await state.clear()
        return
    await state.clear()
    parts = [escape(requisites.bank), f"<code>{escape(requisites.detail)}</code>"]
    if holder:
        parts.append(escape(holder))
    await _done(
        answer_message, panel, order,
        f"✅ Реквизиты по <b>{order.public_id}</b> выданы клиенту\n" + " · ".join(parts),
    )
    await _notify_client(bot, order)


@router.callback_query(SupportAssignRequisites.holder, F.data == "reqholder:skip")
async def support_req_holder_skip(
    callback: CallbackQuery,
    state: FSMContext,
    orders: OrderService,
    db: Database,
    bot: Bot,
    settings: Settings,
    panel: StaffPanel,
) -> None:
    if not _require_support(settings, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await _finish_requisites(
        user_id=callback.from_user.id, holder="",
        answer_message=callback.message,  # type: ignore[arg-type]
        state=state, orders=orders, db=db, bot=bot, panel=panel,
    )


@router.message(SupportAssignRequisites.holder)
async def support_req_finish(
    message: Message,
    state: FSMContext,
    orders: OrderService,
    db: Database,
    bot: Bot,
    settings: Settings,
    panel: StaffPanel,
) -> None:
    if message.from_user is None or not _require_support(settings, message.from_user.id):
        await state.clear()
        return
    holder = (message.text or "").strip()
    if holder == "-":
        holder = ""
    await _finish_requisites(
        user_id=message.from_user.id, holder=holder, answer_message=message,
        state=state, orders=orders, db=db, bot=bot, panel=panel,
    )


@router.callback_query(F.data == "reqcancel")
async def support_req_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Отменено")
    await callback.message.answer(  # type: ignore[union-attr]
        "Выдача реквизитов отменена. Заявка осталась в очереди."
    )


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


@router.callback_query(F.data.startswith("support:extend:"))
async def support_extend_payment(
    callback: CallbackQuery,
    settings: Settings,
    orders: OrderService,
    db: Database,
    bot: Bot,
    panel: StaffPanel,
) -> None:
    """Клиент говорит с банком — продлить срок оплаты."""
    order = await _load_for_action(callback, settings, db, panel)
    if order is None:
        return
    try:
        order = await orders.extend_payment(order, support_tg_id=callback.from_user.id)
    except OrderError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    deadline = (
        order.payment_deadline_at.astimezone(MOSCOW_TZ).strftime("%H:%M")
        if order.payment_deadline_at
        else "—"
    )
    if not is_group_callback(callback):
        await callback.message.answer(  # type: ignore[union-attr]
            f"⏳ Срок оплаты по <b>{order.public_id}</b> продлён до {deadline} МСК",
            parse_mode="HTML",
            reply_markup=support_order_kb(order),
        )
    await _notify_client(
        bot, order, f"⏳ <b>Время на оплату продлено до {deadline} (МСК)</b>\n\n"
    )
    await callback.answer(f"Продлено до {deadline} МСК")


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
    panel: StaffPanel,
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
    done = {
        "reject": "⚠️ Чек отклонён",
        "dispute": "⚖️ Заявка переведена в спор",
    }.get(action, "❌ Заявка отменена")
    await _done(
        message, panel, order,
        f"{done}: <b>{order.public_id}</b>\nПричина: {escape(reason)}",
    )
    # Причина (отклонения чека / отмены) уже есть в карточке клиента
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
