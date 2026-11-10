from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from exchange.config import Settings
from exchange.db import Database
from exchange.keyboards import client_main_kb, client_order_kb
from exchange.rates import RateService
from exchange.services import OrderError, OrderService
from exchange.states import ClientCreateOrder, ClientUploadReceipt
from exchange.statuses import OrderStatus

logger = logging.getLogger(__name__)
router = Router(name="client")


def _parse_amount(text: str) -> float | None:
    cleaned = text.strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
    cleaned = cleaned.replace("₽", "").replace("rub", "").replace("RUB", "")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


@router.message(Command("exchange"))
@router.message(F.text == "Обменять RUB → USDT")
async def start_exchange(
    message: Message, state: FSMContext, settings: Settings, rates: RateService
) -> None:
    await state.set_state(ClientCreateOrder.amount)
    await message.answer(
        f"Введите сумму в рублях.\n"
        f"Лимит: {settings.min_amount_rub:.0f}–{settings.max_amount_rub:.0f} ₽\n"
        f"Курс сейчас: <b>{rates.client_rate():.4f}</b> ₽/USDT\n\n"
        f"Или /cancel чтобы отменить ввод.",
        parse_mode="HTML",
    )


@router.message(Command("cancel"), StateFilter(ClientCreateOrder, ClientUploadReceipt))
async def cancel_fsm(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Ввод отменён.", reply_markup=client_main_kb())


@router.message(ClientCreateOrder.amount)
async def process_amount(
    message: Message, state: FSMContext, settings: Settings, rates: RateService
) -> None:
    amount = _parse_amount(message.text or "")
    if amount is None:
        await message.answer("Нужна сумма числом, например: 15000")
        return
    if amount < settings.min_amount_rub or amount > settings.max_amount_rub:
        await message.answer(
            f"Сумма вне лимита {settings.min_amount_rub:.0f}–{settings.max_amount_rub:.0f} ₽"
        )
        return
    quote = rates.quote_for_amount(amount)
    usdt = round(amount / quote.suggested_rate, 6)
    await state.update_data(amount_rub=amount)
    await state.set_state(ClientCreateOrder.address)
    discount_note = ""
    if quote.amount_discount_rub > 0:
        discount_note = (
            f"\nСкидка по сумме: −{quote.amount_discount_rub:g} к курсу"
        )
    await message.answer(
        f"Сумма: <b>{amount:.2f} ₽</b>\n"
        f"Курс: <b>{quote.suggested_rate:.4f}</b> ₽/USDT{discount_note}\n"
        f"≈ <b>{usdt:.4f} USDT</b>\n\n"
        "Пришлите адрес USDT (TRC-20 / как принимаете)\n"
        "или напишите <b>пропустить</b> / <b>-</b>, если адрес дадите позже "
        "(через саппорта или кнопкой «Указать кошелёк USDT»).",
        parse_mode="HTML",
    )


def _is_skip_address(text: str) -> bool:
    normalized = text.strip().lower().replace("ё", "е")
    return normalized in {
        "-",
        "—",
        "пропустить",
        "пропуск",
        "позже",
        "нет",
        "skip",
        "later",
    }


@router.message(ClientCreateOrder.address)
async def process_address(
    message: Message,
    state: FSMContext,
    orders: OrderService,
    settings: Settings,
    bot: Bot,
) -> None:
    raw = (message.text or "").strip()
    address = "" if _is_skip_address(raw) else raw
    data = await state.get_data()
    amount = float(data["amount_rub"])
    user = message.from_user
    if user is None:
        await message.answer("Не удалось определить пользователя.")
        return
    try:
        order = await orders.create_order(
            client_tg_id=user.id,
            client_username=user.username,
            amount_rub=amount,
            usdt_address=address,
        )
    except OrderError as exc:
        await message.answer(str(exc))
        return

    await state.clear()
    extra = ""
    if not order.has_usdt_address:
        extra = (
            "\n\nАдрес USDT пока не указан — его можно добавить позже "
            "кнопкой «Указать кошелёк USDT» или через саппорта."
        )
    await message.answer(
        "Заявка создана.\n\n"
        + order.short_card()
        + "\n\nСаппорт подберёт реквизиты под ваш запрос. Обычно это занимает несколько минут."
        + extra,
        parse_mode="HTML",
        reply_markup=client_order_kb(order),
    )
    await _notify_staff_new_order(bot, settings, order)


async def _notify_staff_new_order(bot: Bot, settings: Settings, order) -> None:
    from exchange.keyboards import support_order_kb

    targets = set(settings.support_ids) | set(settings.admin_ids)
    text = "🆕 Новая заявка — нужны реквизиты\n\n" + order.short_card(for_support=True)
    for tg_id in targets:
        try:
            await bot.send_message(
                tg_id,
                text,
                parse_mode="HTML",
                reply_markup=support_order_kb(order),
            )
        except Exception:
            logger.exception("Failed to notify staff %s", tg_id)


@router.message(Command("orders"))
@router.message(F.text == "Мои заявки")
async def my_orders(message: Message, db: Database) -> None:
    if message.from_user is None:
        return
    items = await db.list_client_orders(message.from_user.id, limit=5)
    if not items:
        await message.answer("Заявок пока нет. Нажмите «Обменять RUB → USDT».")
        return
    for order in items:
        await message.answer(
            order.short_card(),
            parse_mode="HTML",
            reply_markup=client_order_kb(order),
        )


@router.callback_query(F.data.startswith("client:status:"))
async def client_status(callback: CallbackQuery, db: Database) -> None:
    order_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    order = await db.get_order_by_id(order_id)
    if order is None or callback.from_user.id != order.client_tg_id:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    await callback.message.answer(  # type: ignore[union-attr]
        order.short_card(),
        parse_mode="HTML",
        reply_markup=client_order_kb(order),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("client:cancel:"))
async def client_cancel(
    callback: CallbackQuery, orders: OrderService, db: Database
) -> None:
    order_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    order = await db.get_order_by_id(order_id)
    if order is None or callback.from_user.id != order.client_tg_id:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    try:
        order = await orders.cancel(
            order, reason="Отменена клиентом", by_tg_id=callback.from_user.id
        )
    except OrderError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.message.answer(  # type: ignore[union-attr]
        "Заявка отменена.\n\n" + order.short_card(),
        parse_mode="HTML",
    )
    await callback.answer("Отменено")


@router.callback_query(F.data.startswith("client:upload:"))
async def client_upload_start(
    callback: CallbackQuery, state: FSMContext, db: Database
) -> None:
    order_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    order = await db.get_order_by_id(order_id)
    if order is None or callback.from_user.id != order.client_tg_id:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if order.status not in {
        OrderStatus.AWAITING_PAYMENT,
        OrderStatus.RECEIPT_REJECTED,
    }:
        await callback.answer("Сейчас чек загрузить нельзя", show_alert=True)
        return
    await state.set_state(ClientUploadReceipt.waiting_file)
    await state.update_data(upload_order_id=order.id)
    await callback.message.answer(  # type: ignore[union-attr]
        f"Пришлите чек по заявке <b>{order.public_id}</b> файлом (PDF лучше) или фото.\n"
        f"Сумма к оплате: <b>{order.amount_rub:.2f} ₽</b>\n"
        f"/cancel — отменить загрузку.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ClientUploadReceipt.waiting_file, F.document | F.photo)
async def client_upload_file(
    message: Message,
    state: FSMContext,
    orders: OrderService,
    db: Database,
    bot: Bot,
    settings: Settings,
) -> None:
    data = await state.get_data()
    order_id = int(data["upload_order_id"])
    order = await db.get_order_by_id(order_id)
    if order is None or message.from_user is None or message.from_user.id != order.client_tg_id:
        await state.clear()
        await message.answer("Заявка не найдена.")
        return

    file_id: str
    file_unique_id: str
    filename: str
    mime: str | None

    if message.document:
        file_id = message.document.file_id
        file_unique_id = message.document.file_unique_id
        filename = message.document.file_name or "receipt.bin"
        mime = message.document.mime_type
    else:
        photo = message.photo[-1]
        file_id = photo.file_id
        file_unique_id = photo.file_unique_id
        filename = "receipt.jpg"
        mime = "image/jpeg"

    from io import BytesIO

    downloadable = message.document if message.document else message.photo[-1]
    buffer = await bot.download(downloadable)
    if buffer is None:
        await message.answer("Не удалось скачать файл из Telegram.")
        return
    if isinstance(buffer, BytesIO):
        file_bytes = buffer.getvalue()
    else:
        file_bytes = buffer.read() if hasattr(buffer, "read") else bytes(buffer)

    await message.answer("Чек получен, запускаю автопроверку…")
    try:
        order, result = await orders.submit_receipt(
            order,
            file_id=file_id,
            file_unique_id=file_unique_id,
            file_bytes=file_bytes,
            filename=filename,
            mime_type=mime,
        )
    except OrderError as exc:
        await message.answer(str(exc))
        return

    await state.clear()

    if result.ok:
        text = (
            "✅ Автопроверка пройдена. Заявка ушла саппорту на подтверждение.\n\n"
            + order.short_card()
        )
    else:
        text = (
            "⚠️ Автопроверка не прошла.\n"
            f"Причина: {result.message}\n"
            "Можете загрузить другой чек или дождаться решения саппорта.\n\n"
            + order.short_card()
        )

    await message.answer(text, parse_mode="HTML", reply_markup=client_order_kb(order))
    await _notify_staff_receipt(bot, settings, order, result.ok, result.message)


async def _notify_staff_receipt(
    bot: Bot, settings: Settings, order, ok: bool, message: str
) -> None:
    mark = "✅" if ok else "⚠️"
    text = (
        f"{mark} Чек по {order.public_id}\n"
        f"Автопроверка: {'passed' if ok else 'failed'}\n"
        f"{message}\n\n"
        + order.short_card()
    )
    for tg_id in set(settings.support_ids) | set(settings.admin_ids):
        try:
            await bot.send_message(tg_id, text, parse_mode="HTML")
        except Exception:
            logger.exception("notify receipt failed for %s", tg_id)


@router.message(ClientUploadReceipt.waiting_file)
async def client_upload_wrong(message: Message) -> None:
    await message.answer("Пришлите файл или фото чека, либо /cancel.")
