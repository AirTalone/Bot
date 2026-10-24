"""Process liveness file + optional admin self-ping."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot.config import Settings

logger = logging.getLogger(__name__)


def touch_heartbeat(path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(int(time.time())), encoding="utf-8")


def heartbeat_age_seconds(path: str) -> float | None:
    target = Path(path)
    if not target.exists():
        return None
    return max(0.0, time.time() - target.stat().st_mtime)


async def notify_admins_alive(bot: Bot, settings: Settings, *, reason: str) -> int:
    text = f"Бот на связи ({reason})."
    sent = 0
    for admin_id in settings.admin_id_list:
        try:
            await bot.send_message(admin_id, text)
            sent += 1
        except TelegramAPIError:
            logger.warning("heartbeat notify failed for admin %s", admin_id, exc_info=True)
    return sent
