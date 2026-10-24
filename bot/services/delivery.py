"""Deliver fulfilled access links to buyers."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError

from bot.keyboards import access_granted_keyboard
from bot.models import Order
from bot.texts import access_granted_text

logger = logging.getLogger(__name__)


async def deliver_access_link(bot: Bot, order: Order) -> bool:
    """Send access link to the buyer. Returns True if Telegram accepted the message."""
    try:
        await bot.send_message(
            order.user.telegram_id,
            access_granted_text(order),
            reply_markup=access_granted_keyboard(),
        )
        return True
    except TelegramForbiddenError:
        logger.info("user %s blocked the bot before delivery of order %s", order.user.telegram_id, order.id)
        return False
    except TelegramAPIError:
        logger.exception("failed to deliver access link for order %s", order.id)
        return False
