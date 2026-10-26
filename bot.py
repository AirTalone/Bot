"""
Telegram-бот: пришли ссылку — получи QR-код в стиле СБП.

Запуск:
  1. Создай бота у @BotFather, скопируй токен
  2. Создай файл .env с BOT_TOKEN=...
  3. pip install -r requirements.txt
  4. python bot.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, Message, MessageEntity
from dotenv import load_dotenv

from qr_generator import generate_sbp_qr, is_plausible_url, normalize_url

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

HELP_TEXT = (
    "Пришлите ссылку — я отвечу QR-кодом в стиле СБП.\n\n"
    "Примеры:\n"
    "• https://qr.nspk.ru/AD10...\n"
    "• любая другая https-ссылка\n\n"
    "QR приходит файлом PNG без сжатия Telegram — так банк его нормально читает.\n\n"
    "Команды:\n"
    "/start — приветствие\n"
    "/help — эта подсказка"
)


def _entity_text(text: str, entity: MessageEntity) -> str:
    # Telegram offsets are in UTF-16 code units
    encoded = text.encode("utf-16-le")
    start = entity.offset * 2
    end = (entity.offset + entity.length) * 2
    return encoded[start:end].decode("utf-16-le")


def extract_url(message: Message) -> str | None:
    """Достаёт URL из entities (надёжнее, чем regex по тексту)."""
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []

    for entity in entities:
        if entity.type == "url":
            return _entity_text(text, entity).rstrip(").,;]")
        if entity.type == "text_link" and entity.url:
            return entity.url.strip()

    text = text.strip()
    if not text:
        return None
    match = URL_RE.search(text)
    if match:
        return match.group(0).rstrip(").,;]")
    if is_plausible_url(text):
        return normalize_url(text)
    return None


async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я делаю QR-коды бесплатно и без регистрации.\n\n" + HELP_TEXT
    )


async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


async def handle_text(message: Message) -> None:
    url = extract_url(message)
    if not url:
        await message.answer(
            "Не вижу ссылку. Пришлите URL, например:\n"
            "https://qr.nspk.ru/AD101055EDK5J0E099CQ1IGD7IAVBQK0"
        )
        return

    logger.info("QR request from chat=%s url=%s", message.chat.id, url)

    try:
        png = await asyncio.to_thread(generate_sbp_qr, url)
    except Exception:
        logger.exception("QR generation failed for %s", url)
        await message.answer("Не удалось сгенерировать QR. Попробуйте другую ссылку.")
        return

    # Важно: sendDocument + disable_content_type_detection —
    # иначе Telegram жмёт картинку как фото и банк не читает QR.
    document = BufferedInputFile(png, filename="sbp-qr.png")
    await message.answer_document(
        document=document,
        caption=f"QR готов (PNG без сжатия)\n{url}",
        disable_content_type_detection=True,
    )


async def main() -> None:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "Не задан BOT_TOKEN.\n"
            "Создайте бота у @BotFather и пропишите токен в файле .env:\n"
            "BOT_TOKEN=123456:ABC-DEF..."
        )

    bot = Bot(token=token)
    dp = Dispatcher()
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(handle_text, F.text)

    me = await bot.get_me()
    logger.info("Bot @%s started", me.username)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
