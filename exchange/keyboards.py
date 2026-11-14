from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from exchange.models import Order
from exchange.statuses import OrderStatus


SUPPORT_BUTTON_TEXT = "💬 Поддержка"


def support_contact_kb(username: str) -> InlineKeyboardMarkup | None:
    """Кнопка-ссылка на чат с оператором поддержки."""
    if not username:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Написать в поддержку", url=f"https://t.me/{username}"
                )
            ]
        ]
    )


def no_video_kb() -> InlineKeyboardMarkup:
    """Шаг «видео перевода»: если видео нет."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚫 Нет видео", callback_data="client:novideo")]
        ]
    )


def client_main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Обменять RUB → USDT")],
            [KeyboardButton(text="Мои заявки"), KeyboardButton(text="Курс")],
            [KeyboardButton(text=SUPPORT_BUTTON_TEXT)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def client_back_kb() -> InlineKeyboardMarkup:
    """Одна кнопка «Назад» — выйти из ввода и вернуться в меню."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="« Назад",
                    callback_data="client:back",
                )
            ]
        ]
    )


def client_skip_address_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Указать позже",
                    callback_data="client:skip_address",
                )
            ]
        ]
    )


def client_order_kb(order: Order) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if order.status == OrderStatus.AWAITING_PAYMENT:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Я оплатил",
                    callback_data=f"client:upload:{order.id}",
                )
            ]
        )
    if order.status in {
        OrderStatus.AWAITING_REQUISITES,
        OrderStatus.AWAITING_PAYMENT,
        OrderStatus.RECEIPT_REJECTED,
        OrderStatus.AWAITING_SUPPORT_REVIEW,
        OrderStatus.AWAITING_PAYOUT,
        OrderStatus.DISPUTED,
    } and not order.has_usdt_address:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Указать кошелёк USDT",
                    callback_data=f"wallet:set:{order.id}",
                )
            ]
        )
    if order.status in {
        OrderStatus.AWAITING_REQUISITES,
        OrderStatus.AWAITING_PAYMENT,
        OrderStatus.RECEIPT_REJECTED,
    }:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Отменить заявку",
                    callback_data=f"client:cancel:{order.id}",
                )
            ]
        )
    if order.status == OrderStatus.RECEIPT_REJECTED:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Загрузить другой чек",
                    callback_data=f"client:upload:{order.id}",
                )
            ]
        )
    if order.status in {
        OrderStatus.COMPLETED,
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED,
    }:
        # Заявка закрыта — статус больше не меняется, предлагаем новую
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔁 Создать новую заявку",
                    callback_data="client:new",
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Обновить статус",
                    callback_data=f"client:status:{order.id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def support_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Нужны реквизиты",
                    callback_data="support:queue:need_requisites",
                )
            ],
            [
                InlineKeyboardButton(
                    text="На проверке / reject",
                    callback_data="support:queue:need_review",
                )
            ],
            [
                InlineKeyboardButton(
                    text="В оплате",
                    callback_data="support:queue:in_payment",
                )
            ],
        ]
    )


CLOSED_STATUSES = frozenset(
    {OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.EXPIRED}
)

REVIEW_STATUSES = frozenset(
    {OrderStatus.AWAITING_SUPPORT_REVIEW, OrderStatus.RECEIPT_REJECTED}
)

RATE_EDITABLE = frozenset(
    {
        OrderStatus.AWAITING_REQUISITES,
        OrderStatus.AWAITING_PAYMENT,
        OrderStatus.RECEIPT_REJECTED,
        OrderStatus.AWAITING_SUPPORT_REVIEW,
        OrderStatus.DISPUTED,
    }
)


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _files_row(order: Order) -> list[InlineKeyboardButton]:
    """«🧾 Показать чек» и «🎥 Показать видео» в одну строку."""
    oid = order.id
    row = []
    if order.receipt_file_id:
        row.append(_btn("🧾 Показать чек", f"support:receipt:{oid}"))
    if (order.extra or {}).get("payment_video_file_id"):
        row.append(_btn("🎥 Показать видео", f"support:video:{oid}"))
    return row


def _trust_row(order: Order) -> list[InlineKeyboardButton]:
    """Доверенный клиент — без видео перевода."""
    if (order.extra or {}).get("video_required") is False:
        return [_btn("Убрать из доверенных", f"staff:untrust:{order.id}")]
    return [_btn("⭐ Сделать доверенным", f"staff:trust:{order.id}")]


def staff_order_kb(
    order: Order, *, in_group: bool = False, owner_id: int | None = None
) -> InlineKeyboardMarkup | None:
    """
    Кнопки карточки для сотрудников.
    Сверху — одна главная кнопка этапа, ниже второстепенные по две в ряд.
    in_group=True — карточка в рабочей группе (кнопки «Взять» / «Отпустить», выплата).
    """
    oid = order.id
    rows: list[list[InlineKeyboardButton]] = []

    if order.status in CLOSED_STATUSES:
        files = _files_row(order)
        if files:
            rows.append(files)
        rows.append(_trust_row(order))
        return InlineKeyboardMarkup(inline_keyboard=rows)

    taken = owner_id is not None

    # 1. Главное действие этапа
    if order.status == OrderStatus.AWAITING_REQUISITES:
        if (order.extra or {}).get("margin_ok") is False:
            label = "⚠️ Взять всё равно и выдать реквизиты"
        elif in_group and not taken:
            label = "🙋 Взять и выдать реквизиты"
        else:
            label = "🏦 Выдать реквизиты"
        rows.append([_btn(label, f"support:req:{oid}")])
    elif order.status in REVIEW_STATUSES:
        rows.append([_btn("✅ Одобрить → админу", f"support:approve:{oid}")])
        rows.append(
            [
                _btn("Отклонить чек", f"support:reject:{oid}"),
                _btn("Оплатить заново", f"support:repay:{oid}"),
            ]
        )
    elif order.status == OrderStatus.AWAITING_PAYOUT and in_group:
        rows.append([_btn("💸 Я выплатил USDT", f"admin:payout:{oid}")])
    elif in_group and not taken:
        rows.append([_btn("🙋 Взять заявку", f"staff:take:{oid}")])

    # Клиент говорит с банком — саппорт продлевает срок оплаты (один раз)
    if (
        order.status == OrderStatus.AWAITING_PAYMENT
        and not (order.extra or {}).get("deadline_extended")
    ):
        rows.append([_btn("⏳ Продлить время оплаты", f"support:extend:{oid}")])

    # 2. Курс и кошелёк
    pair = []
    if order.status in RATE_EDITABLE:
        pair.append(_btn("📈 Изменить курс", f"support:rate:{oid}"))
    pair.append(_btn("👛 Кошелёк USDT", f"wallet:set:{oid}"))
    rows.append(pair)

    if order.status == OrderStatus.AWAITING_REQUISITES:
        rows.append([_btn("Отклонить по марже", f"support:reject_margin:{oid}")])
    files = _files_row(order)
    if files:
        rows.append(files)

    # 3. Спор / отмена / доверенный / отпустить
    rows.append(
        [
            _btn("⚖️ Спор", f"support:dispute:{oid}"),
            _btn("❌ Отменить", f"support:cancel:{oid}"),
        ]
    )
    rows.append(_trust_row(order))
    if in_group and taken:
        rows.append([_btn("↩️ Отпустить заявку", f"staff:release:{oid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def support_order_kb(order: Order) -> InlineKeyboardMarkup:
    """Кнопки карточки в личке саппорта."""
    kb = staff_order_kb(order)
    return kb or InlineKeyboardMarkup(inline_keyboard=[])


def staff_card_kb(order: Order, *, owner_id: int | None) -> InlineKeyboardMarkup | None:
    """Кнопки карточки заявки в рабочей группе."""
    return staff_order_kb(order, in_group=True, owner_id=owner_id)


def admin_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="К выплате USDT",
                    callback_data="admin:queue:need_payout",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Споры",
                    callback_data="admin:queue:disputed",
                )
            ],
        ]
    )


def admin_order_kb(order: Order) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if order.status not in {OrderStatus.COMPLETED, OrderStatus.CANCELLED}:
        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        "Указать кошелёк USDT"
                        if not order.has_usdt_address
                        else "Сменить кошелёк USDT"
                    ),
                    callback_data=f"wallet:set:{order.id}",
                )
            ]
        )
    if order.status == OrderStatus.AWAITING_PAYOUT:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Я выплатил USDT",
                    callback_data=f"admin:payout:{order.id}",
                )
            ]
        )
    if order.receipt_file_id:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Показать чек",
                    callback_data=f"admin:receipt:{order.id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Спор",
                callback_data=f"admin:dispute:{order.id}",
            ),
            InlineKeyboardButton(
                text="Отменить",
                callback_data=f"admin:cancel:{order.id}",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
