"""Утилита: ссылка СБП → QR (старый функционал)."""

from __future__ import annotations

import asyncio
import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, Message, MessageEntity

from qr_generator import generate_sbp_qr, is_plausible_url, normalize_url

logger = logging.getLogger(__name__)
router = Router(name="qr_tool")

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


class QrMode(StatesGroup):
    waiting_url = State()


def _entity_text(text: str, entity: MessageEntity) -> str:
    encoded = text.encode("utf-16-le")
    start = entity.offset * 2
    end = (entity.offset + entity.length) * 2
    return encoded[start:end].decode("utf-16-le")


def extract_url(message: Message) -> str | None:
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


@router.message(Command("qr"))
async def qr_start(message: Message, state: FSMContext) -> None:
    await state.set_state(QrMode.waiting_url)
    await message.answer(
        "Пришлите ссылку СБП (https://qr.nspk.ru/...) — сделаю QR.\n/cancel — выход."
    )


@router.message(Command("cancel"), StateFilter(QrMode))
async def qr_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Режим QR выключен.")


@router.message(QrMode.waiting_url, F.text)
async def qr_make(message: Message, state: FSMContext) -> None:
    url = extract_url(message)
    if not url:
        await message.answer("Не вижу ссылку.")
        return
    try:
        png = await asyncio.to_thread(generate_sbp_qr, url)
    except Exception:
        logger.exception("QR failed")
        await message.answer("Не удалось сгенерировать QR.")
        return
    await state.clear()
    await message.answer_document(
        document=BufferedInputFile(png, filename="sbp-qr.png"),
        caption=url,
        disable_content_type_detection=True,
    )
