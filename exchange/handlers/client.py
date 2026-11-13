from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from exchange.client_card import client_card, fmt_rub, fmt_usdt
from exchange.config import Settings
from exchange.staff_card import staff_card
from exchange.db import Database
from exchange.handlers.common import welcome_text
from exchange.keyboards import (
    client_back_kb,
    client_main_kb,
    client_order_kb,
    client_skip_address_kb,
)
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
        _amount_prompt(settings, rates),
        parse_mode="HTML",
        reply_markup=client_back_kb(),
    )


def _amount_prompt(settings: Settings, rates: RateService, error: str = "") -> str:
    """Экран «Сколько рублей хотите обменять?» (с ошибкой сверху, если ввели не то)."""
    lines = [
        f"Курс: <b>{rates.client_rate():.2f} ₽</b> за 1 USDT",
        f"Сумма: от {fmt_rub(settings.min_amount_rub)} "
        f"до {fmt_rub(settings.max_amount_rub)} ₽",
    ]
    if settings.amount_discount_30k > 0:
        lines.append(
            f"Свыше {fmt_rub(settings.amount_tier_30k)} ₽ — курс лучше "
            f"на {settings.amount_discount_30k:g} ₽"
        )
    if settings.amount_discount_40k > 0:
        lines.append(
            f"Свыше {fmt_rub(settings.amount_tier_40k)} ₽ — курс лучше "
            f"на {settings.amount_discount_40k:g} ₽"
        )
    text = (
        "💰 <b>Сколько рублей хотите обменять?</b>\n\n"
        "<blockquote>" + "\n".join(lines) + "</blockquote>\n\n"
        "Напишите сумму числом, например: 15000"
    )
    if error:
        text = f"⚠️ {error}\n\n" + text
    return text


@router.callback_query(F.data == "client:back")
async def back_to_menu(
    callback: CallbackQuery, state: FSMContext, settings: Settings, rates: RateService
) -> None:
    # 1. Бот перестаёт ждать от клиента сумму
    await state.clear()
    # 2. Убираем кнопку из старого сообщения, чтобы её не нажали второй раз
    try:
        await callback.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
    except Exception:
        pass
    # 3. Показываем главное меню (то же, что по /start)
    await callback.message.answer(  # type: ignore[union-attr]
        welcome_text(settings, callback.from_user.id, rates),
        reply_markup=client_main_kb(),
        parse_mode="HTML",
    )
    # 4. Сообщаем Telegram, что нажатие обработано (иначе на кнопке крутятся «часики»)
    await callback.answer()


@router.message(Command("cancel"), StateFilter(ClientCreateOrder, ClientUploadReceipt))
async def cancel_fsm(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Ввод отменён.", reply_markup=client_main_kb())


@router.message(ClientCreateOrder.amount)
async def process_amount(
    message: Message, state: FSMContext, settings: Settings, rates: RateService
) -> None:
    amount = _parse_amount(message.text or "")
    error = ""
    if amount is None:
        error = "Не получилось распознать сумму. Напишите только число."
    elif amount < settings.min_amount_rub:
        error = f"Минимальная сумма — {fmt_rub(settings.min_amount_rub)} ₽."
    elif amount > settings.max_amount_rub:
        error = f"Максимальная сумма — {fmt_rub(settings.max_amount_rub)} ₽."
    if error:
        await message.answer(
            _amount_prompt(settings, rates, error),
            parse_mode="HTML",
            reply_markup=client_back_kb(),
        )
        return
    quote = rates.quote_for_amount(amount)
    usdt = amount / quote.suggested_rate
    await state.update_data(amount_rub=amount)
    await state.set_state(ClientCreateOrder.address)
    discount_note = ""
    if quote.amount_discount_rub > 0:
        discount_note = (
            f"\nСкидка по сумме: −{quote.amount_discount_rub:g} к курсу"
        )
    await message.answer(
        f"Сумма: <b>{fmt_rub(amount)} ₽</b>\n"
        f"Курс: <b>{quote.suggested_rate:.2f} ₽</b> за 1 USDT{discount_note}\n"
        f"≈ <b>{fmt_usdt(usdt)} USDT</b>\n\n"
        "Пришлите адрес USDT (TRC-20)\n"
        "или нажмите «Указать позже».",
        parse_mode="HTML",
        reply_markup=client_skip_address_kb(),
    )


def _is_skip_address(text: str) -> bool:
    normalized = text.strip().lower().replace("ё", "е")
    return normalized in {
        "-",
        "—",
        "пропустить",
        "пропуск",
        "указать позже",
        "позже",
        "нет",
        "skip",
        "later",
    }


async def _finish_create_order(
    *,
    state: FSMContext,
    orders: OrderService,
    settings: Settings,
    bot: Bot,
    user_id: int,
    username: str | None,
    amount_rub: float,
    usdt_address: str,
    answer,
) -> None:
    try:
        order = await orders.create_order(
            client_tg_id=user_id,
            client_username=username,
            amount_rub=amount_rub,
            usdt_address=usdt_address,
        )
    except OrderError as exc:
        await answer(str(exc))
        return

    await state.clear()
    await answer(
        client_card(order),
        parse_mode="HTML",
        reply_markup=client_order_kb(order),
    )
    await _notify_staff_new_order(bot, settings, order)


@router.callback_query(F.data == "client:skip_address", StateFilter(ClientCreateOrder.address))
async def skip_address_callback(
    callback: CallbackQuery,
    state: FSMContext,
    orders: OrderService,
    settings: Settings,
    bot: Bot,
) -> None:
    data = await state.get_data()
    if "amount_rub" not in data:
        await callback.answer("Сначала введите сумму", show_alert=True)
        return
    user = callback.from_user
    await callback.answer()
    await _finish_create_order(
        state=state,
        orders=orders,
        settings=settings,
        bot=bot,
        user_id=user.id,
        username=user.username,
        amount_rub=float(data["amount_rub"]),
        usdt_address="",
        answer=callback.message.answer,  # type: ignore[union-attr]
    )


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
    await _finish_create_order(
        state=state,
        orders=orders,
        settings=settings,
        bot=bot,
        user_id=user.id,
        username=user.username,
        amount_rub=amount,
        usdt_address=address,
        answer=message.answer,
    )


async def _notify_staff_new_order(bot: Bot, settings: Settings, order) -> None:
    from exchange.keyboards import support_order_kb

    if settings.staff_chat_id is not None:
        return  # есть рабочая группа — карточка придёт туда
    targets = set(settings.support_ids) | set(settings.admin_ids)
    text = "🆕 Новая заявка — нужны реквизиты\n\n" + staff_card(order)
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
            client_card(order),
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
    # Обновляем это же сообщение, а не шлём новое
    try:
        await callback.message.edit_text(  # type: ignore[union-attr]
            client_card(order),
            parse_mode="HTML",
            reply_markup=client_order_kb(order),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            await callback.answer("Статус не изменился")
            return
        # Старое сообщение нельзя отредактировать — присылаем новое
        await callback.message.answer(  # type: ignore[union-attr]
            client_card(order),
            parse_mode="HTML",
            reply_markup=client_order_kb(order),
        )
    await callback.answer("Обновлено")


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
        client_card(order),
        parse_mode="HTML",
        reply_markup=client_order_kb(order),
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

    wait_msg = await message.answer("Чек получен, запускаю автопроверку…")
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
    finally:
        # Промежуточное сообщение заменяется результатом
        try:
            await wait_msg.delete()
        except Exception:
            pass

    await state.clear()

    # Статус и причина (если чек не прошёл) уже есть в карточке
    await message.answer(
        client_card(order), parse_mode="HTML", reply_markup=client_order_kb(order)
    )
    await _notify_staff_receipt(bot, settings, order, result.ok, result.message)


async def _notify_staff_receipt(
    bot: Bot, settings: Settings, order, ok: bool, message: str
) -> None:
    if settings.staff_chat_id is not None:
        return  # есть рабочая группа — карточка там «всплывёт» с уведомлением
    mark = "✅" if ok else "⚠️"
    text = (
        f"{mark} Чек по {order.public_id}\n"
        f"Автопроверка: {'passed' if ok else 'failed'}\n"
        f"{message}\n\n"
        + staff_card(order)
    )
    for tg_id in set(settings.support_ids) | set(settings.admin_ids):
        try:
            await bot.send_message(tg_id, text, parse_mode="HTML")
        except Exception:
            logger.exception("notify receipt failed for %s", tg_id)


@router.message(ClientUploadReceipt.waiting_file)
async def client_upload_wrong(message: Message) -> None:
    await message.answer("Пришлите файл или фото чека, либо /cancel.")
