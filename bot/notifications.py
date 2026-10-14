import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup

from bot.config import Settings

logger = logging.getLogger(__name__)


async def notify_admins(
    bot: Bot,
    settings: Settings,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> int:
    delivered = 0
    for admin_id in settings.admin_id_list:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
        except TelegramAPIError:
            logger.exception("failed to notify admin %s", admin_id)
            continue
        delivered += 1
    return delivered
