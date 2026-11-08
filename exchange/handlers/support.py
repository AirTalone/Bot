from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from exchange.config import Settings
from exchange.db import Database
from exchange.keyboards import client_order_kb, support_home_kb, support_order_kb
from exchange.models import Requisites
from exchange.services import OrderError, OrderService
from exchange.states import SupportAssignRequisites, SupportNote
from exchange.statuses import SUPPORT_QUEUES
from qr_generator import generate_sbp_qr, is_plausible_url, normalize_url

logger = logging.getLogger(__name__)
router = Router(name="support")


def _require_support(settings: Settings, user_id: int) -> bool:
    return settings.is_support(user_id)


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
            order.short_card(),
            parse_mode="HTML",
            reply_markup=support_order_kb(order),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("support:req:"))
async def support_req_start(
    callback: CallbackQuery, state: FSMContext, settings: Settings, db: Database
) -> None:
    if not _require_support(settings, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    order_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    order = await db.get_order_by_id(order_id)
    if order is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await state.set_state(SupportAssignRequisites.bank)
    await state.update_data(req_order_id=order.id)
    await callback.message.answer(  # type: ignore[union-attr]
        f"Выдача реквизитов для <b>{order.public_id}</b> "
        f"({order.amount_rub:.2f} ₽).\n"
        f"1/4 — название банка (как на площадке):",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(SupportAssignRequisites.bank)
async def support_req_bank(message: Message, state: FSMContext) -> None:
    await state.update_data(bank=(message.text or "").strip())
    await state.set_state(SupportAssignRequisites.detail)
    await message.answer("2/4 — реквизиты (телефон СБП / карта / счёт):")


@router.message(SupportAssignRequisites.detail)
async def support_req_detail(message: Message, state: FSMContext) -> None:
    await state.update_data(detail=(message.text or "").strip())
    await state.set_state(SupportAssignRequisites.holder)
    await message.answer("3/4 — ФИО / получатель (или «-» если нет):")


@router.message(SupportAssignRequisites.holder)
async def support_req_holder(message: Message, state: FSMContext) -> None:
    holder = (message.text or "").strip()
    if holder == "-":
        holder = ""
    await state.update_data(holder=holder)
    await state.set_state(SupportAssignRequisites.sbp_url)
    await message.answer(
        "4/4 — ссылка СБП (https://qr.nspk.ru/...) или «-» если нет:"
    )


@router.message(SupportAssignRequisites.sbp_url)
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
    raw_url = (message.text or "").strip()
    sbp_url = ""
    if raw_url != "-":
        if is_plausible_url(raw_url):
            sbp_url = normalize_url(raw_url)
        else:
            await message.answer("Это не похоже на ссылку. Пришлите URL или «-».")
            return

    data = await state.get_data()
    order = await db.get_order_by_id(int(data["req_order_id"]))
    if order is None:
        await state.clear()
        await message.answer("Заявка исчезла.")
        return

    requisites = Requisites(
        bank=str(data.get("bank") or ""),
        detail=str(data.get("detail") or ""),
        holder=str(data.get("holder") or ""),
        sbp_url=sbp_url,
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
        "Реквизиты выданы клиенту.\n\n" + order.short_card(),
        parse_mode="HTML",
        reply_markup=support_order_kb(order),
    )

    client_text = (
        f"Реквизиты по заявке <b>{order.public_id}</b>\n\n"
        f"Сумма к оплате: <b>{order.amount_rub:.2f} ₽</b>\n"
        f"Банк: {order.requisites_bank or '—'}\n"
        f"Реквизиты: <code>{order.requisites_detail}</code>\n"
    )
    if order.requisites_holder:
        client_text += f"Получатель: {order.requisites_holder}\n"
    if order.payment_deadline_at:
        client_text += (
            f"\nОплатите до: <b>{order.payment_deadline_at.strftime('%H:%M:%S UTC')}</b>\n"
            f"(таймер {settings.payment_ttl_minutes} мин)\n"
        )
    client_text += "\nПосле оплаты нажмите кнопку «Я оплатил»."

    try:
        await bot.send_message(
            order.client_tg_id,
            client_text,
            parse_mode="HTML",
            reply_markup=client_order_kb(order),
        )
        if order.requisites_sbp_url:
            png = generate_sbp_qr(order.requisites_sbp_url)
            await bot.send_document(
                order.client_tg_id,
                document=BufferedInputFile(png, filename="sbp-qr.png"),
                caption=order.requisites_sbp_url,
                disable_content_type_detection=True,
                reply_markup=client_order_kb(order),
            )
    except Exception:
        logger.exception("Failed to notify client %s", order.client_tg_id)


@router.callback_query(F.data.startswith("support:approve:"))
async def support_approve(
    callback: CallbackQuery,
    settings: Settings,
    orders: OrderService,
    db: Database,
    bot: Bot,
) -> None:
    if not _require_support(settings, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    order_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    order = await db.get_order_by_id(order_id)
    if order is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    try:
        order = await orders.support_approve(
            order, support_tg_id=callback.from_user.id, note="Одобрено саппортом"
        )
    except OrderError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.message.answer(  # type: ignore[union-attr]
        "Одобрено → очередь выплаты админу.\n\n" + order.short_card(),
        parse_mode="HTML",
        reply_markup=support_order_kb(order),
    )
    try:
        await bot.send_message(
            order.client_tg_id,
            f"Саппорт подтвердил оплату по <b>{order.public_id}</b>.\n"
            "Ожидайте выплату USDT от администратора.",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("client notify approve failed")

    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                "💸 Нужна выплата USDT\n\n" + order.short_card(),
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("admin notify failed")
    await callback.answer("Одобрено")


@router.callback_query(F.data.startswith("support:reject:"))
async def support_reject_start(
    callback: CallbackQuery, state: FSMContext, settings: Settings, db: Database
) -> None:
    if not _require_support(settings, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    order_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    order = await db.get_order_by_id(order_id)
    if order is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await state.set_state(SupportNote.waiting)
    await state.update_data(note_order_id=order.id, note_action="reject")
    await callback.message.answer("Укажите причину отклонения чека:")  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data.startswith("support:repay:"))
async def support_repay(
    callback: CallbackQuery,
    settings: Settings,
    orders: OrderService,
    db: Database,
    bot: Bot,
) -> None:
    if not _require_support(settings, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    order_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    order = await db.get_order_by_id(order_id)
    if order is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    try:
        order = await orders.support_request_new_payment(
            order, support_tg_id=callback.from_user.id
        )
    except OrderError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.message.answer(  # type: ignore[union-attr]
        "Клиенту запрошена повторная оплата/чек.\n\n" + order.short_card(),
        parse_mode="HTML",
        reply_markup=support_order_kb(order),
    )
    try:
        await bot.send_message(
            order.client_tg_id,
            f"Саппорт просит повторно оплатить / прислать чек по <b>{order.public_id}</b>.",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("repay notify failed")
    await callback.answer()


@router.callback_query(F.data.startswith("support:dispute:"))
@router.callback_query(F.data.startswith("support:cancel:"))
async def support_dispute_or_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
) -> None:
    if not _require_support(settings, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    parts = callback.data.split(":")  # type: ignore[union-attr]
    action, order_id = parts[1], int(parts[2])
    await state.set_state(SupportNote.waiting)
    await state.update_data(note_order_id=order_id, note_action=action)
    prompt = "Причина спора:" if action == "dispute" else "Причина отмены:"
    await callback.message.answer(prompt)  # type: ignore[union-attr]
    await callback.answer()


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
            client_msg = (
                f"Саппорт отклонил чек по <b>{order.public_id}</b>.\nПричина: {reason}\n"
                "Можете загрузить другой чек."
            )
        elif action == "dispute":
            order = await orders.mark_disputed(order, reason=reason)
            client_msg = f"Заявка <b>{order.public_id}</b> переведена в спор."
        else:
            order = await orders.cancel(
                order, reason=reason, by_tg_id=message.from_user.id
            )
            client_msg = f"Заявка <b>{order.public_id}</b> отменена.\nПричина: {reason}"
    except OrderError as exc:
        await message.answer(str(exc))
        await state.clear()
        return

    await state.clear()
    await message.answer(order.short_card(), parse_mode="HTML", reply_markup=support_order_kb(order))
    try:
        await bot.send_message(order.client_tg_id, client_msg, parse_mode="HTML")
    except Exception:
        logger.exception("support note client notify failed")


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
    await bot.send_document(
        callback.from_user.id,
        document=order.receipt_file_id,
        caption=f"Чек {order.public_id}",
    )
    await callback.answer()
