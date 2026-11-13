"""
«Один экран»: каждое действие пользователя заменяет прошлое сообщение бота.

Как работает:
- Каждый апдейт от пользователя (сообщение или нажатие кнопки) — новый «шаг».
- Когда бот в ответ на шаг отправляет первое сообщение в чат этого пользователя,
  сообщения прошлого шага удаляются (и сообщение, на кнопку которого нажали).
- Если в одном шаге бот шлёт несколько сообщений (например, список заявок),
  они все остаются до следующего шага.
- Уведомления в чужие чаты и из фоновых задач (реквизиты клиенту, выплата,
  новая заявка саппорту, истечение таймера) не удаляются автоматически.
- Сообщение с нижней клавиатурой меню (ReplyKeyboardMarkup) не удаляется
  следующим шагом: если его удалить, Telegram убирает и клавиатуру. Оно
  заменяется только следующим сообщением с меню.
- Сообщение пользователя (текст, команда, кнопка меню) удаляется, когда бот
  на него ответил. Файлы и фото (чеки) остаются.

Учёт хранится в памяти: после перезапуска бота старые сообщения не удаляются.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.methods import SendDocument, SendMessage, SendPhoto
from aiogram.methods.base import TelegramMethod, TelegramType
from aiogram.types import Message, ReplyKeyboardMarkup, TelegramObject, Update

logger = logging.getLogger(__name__)

# Какие отправки считаются «экраном» бота
SCREEN_METHODS = (SendMessage, SendDocument, SendPhoto)


@dataclass(frozen=True)
class Step:
    """Текущий шаг: от кого пришёл апдейт и на какое сообщение нажали."""

    chat_id: int
    token: object = field(default_factory=object, compare=False)
    pressed_message_id: int | None = None
    # Текстовое сообщение пользователя этого шага — удаляется вместе с прошлым экраном
    user_message_id: int | None = None
    # Кто действует. Для лички = chat_id; для группы — ID нажавшего сотрудника
    user_id: int | None = None

    @property
    def private_chat_id(self) -> int:
        """Личный чат того, кто действует: только здесь бот заменяет сообщения."""
        return self.user_id if self.user_id is not None else self.chat_id


_current_step: ContextVar[Step | None] = ContextVar("screen_step", default=None)


@dataclass
class _Screen:
    token: object
    message_ids: list[int] = field(default_factory=list)


class ScreenTracker:
    """Помнит последние сообщения бота в каждом чате и решает, что удалить."""

    def __init__(self) -> None:
        self._screens: dict[int, _Screen] = {}
        self._menu_anchor: dict[int, int] = {}

    def register_sent(
        self, *, step: Step | None, chat_id: int, message_id: int, is_menu: bool
    ) -> list[int]:
        """Учесть отправленное сообщение. Возвращает id сообщений к удалению."""
        if step is None or step.private_chat_id != chat_id:
            # Уведомление в чужой чат, в группу или из фона — не трогаем.
            return []
        # Шаг пришёл из этой же лички (а не из группы, откуда вопрос ушёл в личку)
        same_chat = step.chat_id == chat_id

        to_delete: list[int] = []
        screen = self._screens.get(chat_id)
        if screen is None or screen.token is not step.token:
            # Первое сообщение нового шага → убрать прошлый шаг.
            if screen is not None:
                to_delete.extend(screen.message_ids)
            if same_chat and step.pressed_message_id is not None:
                to_delete.append(step.pressed_message_id)
            if same_chat and step.user_message_id is not None:
                to_delete.append(step.user_message_id)
            screen = _Screen(token=step.token)
            self._screens[chat_id] = screen

        if is_menu:
            old_anchor = self._menu_anchor.get(chat_id)
            if old_anchor is not None:
                to_delete.append(old_anchor)
            self._menu_anchor[chat_id] = message_id
        else:
            screen.message_ids.append(message_id)

        keep = {message_id, self._menu_anchor.get(chat_id)}
        result: list[int] = []
        for mid in to_delete:
            if mid not in keep and mid not in result:
                result.append(mid)
        return result


def _step_from_update(update: Update) -> Step | None:
    if update.message is not None:
        msg = update.message
        if msg.chat.type != "private":
            return None  # сообщения в группе ничего не заменяют
        # Файлы, фото и видео (чеки, видео перевода) не удаляем —
        # только то, что пользователь написал
        is_file = bool(msg.document or msg.photo or msg.video or msg.video_note)
        return Step(
            chat_id=msg.chat.id,
            user_message_id=None if is_file else msg.message_id,
        )
    if update.callback_query is not None:
        cb = update.callback_query
        cb_msg = cb.message
        if cb_msg is None:
            return None
        if cb_msg.chat.type != "private":
            # Кнопка в рабочей группе: в группе ничего не удаляем,
            # но вопрос в личке сотрудника заменит его прошлый экран.
            return Step(chat_id=cb_msg.chat.id, user_id=cb.from_user.id)
        return Step(chat_id=cb_msg.chat.id, pressed_message_id=cb_msg.message_id)
    return None


class ScreenStepMiddleware(BaseMiddleware):
    """Отмечает начало нового шага для каждого апдейта."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        step = _step_from_update(event) if isinstance(event, Update) else None
        token = _current_step.set(step)
        try:
            return await handler(event, data)
        finally:
            _current_step.reset(token)


class ScreenRequestMiddleware(BaseRequestMiddleware):
    """После каждой отправки удаляет сообщения прошлого шага."""

    def __init__(self, tracker: ScreenTracker) -> None:
        self.tracker = tracker

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ):
        result = await make_request(bot, method)
        if isinstance(method, SCREEN_METHODS) and isinstance(result, Message):
            try:
                to_delete = self.tracker.register_sent(
                    step=_current_step.get(),
                    chat_id=result.chat.id,
                    message_id=result.message_id,
                    is_menu=isinstance(method.reply_markup, ReplyKeyboardMarkup),
                )
                for mid in to_delete:
                    try:
                        await bot.delete_message(chat_id=result.chat.id, message_id=mid)
                    except Exception:
                        # Уже удалено / старше 48 ч — просто пропускаем.
                        logger.debug("delete_message %s failed", mid)
            except Exception:
                logger.exception("screen replace failed")
        return result


def setup_screen(bot: Bot, dp) -> ScreenTracker:
    tracker = ScreenTracker()
    bot.session.middleware(ScreenRequestMiddleware(tracker))
    dp.update.outer_middleware(ScreenStepMiddleware())
    return tracker
