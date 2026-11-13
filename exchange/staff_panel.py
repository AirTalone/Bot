"""
Панель сотрудников в рабочей группе Telegram (STAFF_CHAT_ID).

- Каждая заявка — одна карточка в группе. При изменении заявки карточка
  редактируется на месте.
- Когда заявка требует действия (новая, пришёл чек, нужна выплата, спор),
  старая карточка удаляется и присылается заново внизу — чтобы сотрудники
  получили уведомление (правка сообщения уведомлений не даёт).
- Кнопка «Взять» закрепляет заявку за сотрудником; остальные не могут по ней
  действовать (админ — может всегда).
- Ввод текста (реквизиты, причины, TxID) идёт в личке сотрудника с ботом,
  чтобы не засорять группу.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import CallbackQuery, User

from exchange.config import Settings
from exchange.db import Database
from exchange.keyboards import staff_card_kb
from exchange.models import Order
from exchange.staff_card import staff_card
from exchange.statuses import OrderStatus

logger = logging.getLogger(__name__)

# На этих статусах карточка «всплывает» вниз с уведомлением
ATTENTION_STATUSES = frozenset(
    {
        OrderStatus.AWAITING_REQUISITES,
        OrderStatus.AWAITING_SUPPORT_REVIEW,
        OrderStatus.RECEIPT_REJECTED,
        OrderStatus.AWAITING_PAYOUT,
        OrderStatus.DISPUTED,
    }
)

def display_name(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    return user.full_name or str(user.id)


def staff_card_text(order: Order, owner: tuple[int, str] | None) -> str:
    return staff_card(order, owner=owner, show_owner=True)


class StaffPanel:
    def __init__(self, bot: Bot, settings: Settings, db: Database) -> None:
        self.bot = bot
        self.settings = settings
        self.db = db

    @property
    def enabled(self) -> bool:
        return self.settings.staff_chat_id is not None

    async def sync(self, order: Order) -> None:
        """Создать / обновить карточку заявки в группе."""
        if not self.enabled:
            return
        chat_id = int(self.settings.staff_chat_id)  # type: ignore[arg-type]
        owner = await self.db.get_owner(order.id)
        text = staff_card_text(order, owner)
        kb = staff_card_kb(order, owner_id=owner[0] if owner else None)
        card = await self.db.get_staff_card(order.id)

        status_changed = card is None or card[2] != order.status.value
        bump = card is None or (status_changed and order.status in ATTENTION_STATUSES)

        if card is not None and card[0] == chat_id and not bump:
            try:
                await self.bot.edit_message_text(
                    text,
                    chat_id=chat_id,
                    message_id=card[1],
                    parse_mode="HTML",
                    reply_markup=kb,
                )
                if status_changed:
                    await self.db.set_staff_card(
                        order.id, chat_id=chat_id, message_id=card[1],
                        status=order.status.value,
                    )
                return
            except TelegramBadRequest as exc:
                if "message is not modified" in str(exc):
                    return
                # Сообщение удалено / недоступно — пришлём новое
                logger.warning("staff card edit failed for %s: %s", order.public_id, exc)

        if card is not None:
            try:
                await self.bot.delete_message(chat_id=card[0], message_id=card[1])
            except Exception:
                pass  # старше 48 ч или уже удалено — просто оставляем

        try:
            msg = await self.bot.send_message(
                chat_id, text, parse_mode="HTML", reply_markup=kb
            )
        except Exception:
            logger.exception("staff card send failed for %s", order.public_id)
            return
        await self.db.set_staff_card(
            order.id, chat_id=chat_id, message_id=msg.message_id,
            status=order.status.value,
        )

    async def ensure_owner(self, order: Order, user: User) -> str | None:
        """
        Проверить, может ли сотрудник действовать по заявке.
        Свободную заявку автоматически закрепляет за ним.
        Возвращает текст ошибки или None, если можно.
        """
        owner = await self.db.get_owner(order.id)
        if owner is None:
            owner = await self.db.take_order(
                order.id, tg_id=user.id, name=display_name(user)
            )
            await self.sync(order)
        if owner[0] == user.id or self.settings.is_admin(user.id):
            return None
        return f"Заявку ведёт {owner[1]}"


def dm_state(state: FSMContext, bot: Bot, user_id: int) -> FSMContext:
    """Состояние диалога в личке сотрудника (даже если кнопку нажали в группе)."""
    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=state.storage, key=key)


async def start_staff_input(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    *,
    new_state: State,
    data: dict,
    text: str,
) -> bool:
    """
    Начать ввод текста в личке с ботом. Если кнопку нажали в группе —
    вопрос придёт в личные сообщения.
    """
    user_id = callback.from_user.id
    ctx = dm_state(state, bot, user_id)
    await ctx.set_state(new_state)
    await ctx.set_data(data)
    try:
        await bot.send_message(user_id, text, parse_mode="HTML")
    except (TelegramForbiddenError, TelegramBadRequest):
        await ctx.clear()
        await callback.answer(
            "Откройте личный чат с ботом, нажмите /start и повторите.",
            show_alert=True,
        )
        return False
    in_group = callback.message is not None and callback.message.chat.type != "private"
    await callback.answer("Продолжим в личке с ботом 👉" if in_group else None)
    return True


async def send_receipt(callback: CallbackQuery, bot: Bot, order: Order, kb) -> None:
    """Прислать чек сотруднику в личку (файл или фото)."""
    user_id = callback.from_user.id
    caption = f"Чек {order.public_id}"
    try:
        try:
            await bot.send_document(
                user_id, document=order.receipt_file_id, caption=caption, reply_markup=kb
            )
        except TelegramBadRequest:
            # Клиент прислал фото — его нельзя отправить как документ
            await bot.send_photo(
                user_id, photo=order.receipt_file_id, caption=caption, reply_markup=kb
            )
    except (TelegramForbiddenError, TelegramBadRequest):
        await callback.answer(
            "Не получилось отправить чек в личку. Откройте чат с ботом, "
            "нажмите /start и повторите.",
            show_alert=True,
        )
        return
    await callback.answer("Чек отправлен вам в личку" if is_group_callback(callback) else None)


def is_group_callback(callback: CallbackQuery) -> bool:
    return callback.message is not None and callback.message.chat.type != "private"
