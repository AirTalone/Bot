from datetime import UTC, datetime, timedelta

import httpx
import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ChatType, ParseMode
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import Chat, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.models import OrderStatus
from bot.services.orders import create_order, list_active_tariffs, upsert_user
from bot.services.panel.marzban import MarzbanClient
from bot.services.stars import (
    STARS_CURRENCY,
    decode_stars_payload,
    encode_stars_payload,
    validate_stars_payment,
)
from bot.services.stars_fulfill import apply_stars_payment


def test_payload_roundtrip() -> None:
    raw = encode_stars_payload(order_id=12, payment_code="VPN-ABC123")
    parsed = decode_stars_payload(raw)
    assert parsed is not None
    assert parsed.order_id == 12
    assert parsed.payment_code == "VPN-ABC123"
    assert decode_stars_payload("bad") is None


def test_validate_stars_payment_amount_and_status() -> None:
    assert (
        validate_stars_payment(
            currency=STARS_CURRENCY,
            total_amount=75,
            expected_amount=75,
            order_status=OrderStatus.awaiting_payment.value,
            order_payment_code="VPN-A",
            payload_code="VPN-A",
        )
        is None
    )
    assert (
        validate_stars_payment(
            currency=STARS_CURRENCY,
            total_amount=10,
            expected_amount=75,
            order_status=OrderStatus.awaiting_payment.value,
            order_payment_code="VPN-A",
            payload_code="VPN-A",
        )
        is not None
    )
    assert (
        validate_stars_payment(
            currency="RUB",
            total_amount=75,
            expected_amount=75,
            order_status=OrderStatus.awaiting_payment.value,
            order_payment_code="VPN-A",
            payload_code="VPN-A",
        )
        is not None
    )


class _FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[TelegramType]] = []

    async def close(self) -> None:
        return None

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        name = type(method).__name__
        if name == "SendMessage":
            return Message(
                message_id=len(self.calls),
                date=datetime.now(UTC),
                chat=Chat(id=method.chat_id, type=ChatType.PRIVATE),
                text=method.text,
            )
        raise AssertionError(f"unexpected {name}")


@pytest.mark.asyncio
async def test_apply_stars_payment_idempotent_and_auto_fulfill(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tariffs = await list_active_tariffs(session)
    tariff = tariffs[0]
    tariff.stars_price = 75
    user = await upsert_user(session, telegram_id=9001, username="star", full_name="Star")
    order = await create_order(session, user, tariff, payment_method="stars", stars_amount=75)
    await session.commit()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/admin/token":
            return httpx.Response(200, json={"access_token": "tok"})
        if request.method == "GET":
            return httpx.Response(404, json={"detail": "missing"})
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "username": "tg9001",
                    "subscription_url": "https://panel.test/sub/stars",
                    "expire": int((datetime.now(UTC) + timedelta(days=30)).timestamp()),
                },
            )
        return httpx.Response(500, text="no")

    def _build(settings: Settings):
        return MarzbanClient(
            base_url="https://panel.test",
            username="admin",
            password="secret",
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr("bot.services.stars_fulfill.build_panel_client", _build)

    settings = Settings(
        bot_token="1:TEST",
        admin_ids="1",
        stars_enabled=True,
        panel_enabled=True,
        panel_provider="marzban",
        panel_base_url="https://panel.test",
        panel_username="admin",
        panel_password="secret",
    )
    fake = _FakeSession()
    bot = Bot(token=settings.bot_token, session=fake, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    payload = encode_stars_payload(order_id=order.id, payment_code=order.payment_code)
    charge = "charge-abc"

    first = await apply_stars_payment(
        session,
        bot,
        settings,
        user_id=user.telegram_id,
        currency=STARS_CURRENCY,
        total_amount=75,
        invoice_payload=payload,
        telegram_payment_charge_id=charge,
    )
    assert first is not None
    assert first.status == OrderStatus.fulfilled.value
    assert first.access_link == "https://panel.test/sub/stars"
    assert first.telegram_payment_charge_id == charge

    second = await apply_stars_payment(
        session,
        bot,
        settings,
        user_id=user.telegram_id,
        currency=STARS_CURRENCY,
        total_amount=75,
        invoice_payload=payload,
        telegram_payment_charge_id=charge,
    )
    assert second is not None
    assert second.id == first.id
    assert second.status == OrderStatus.fulfilled.value
    await bot.session.close()


@pytest.mark.asyncio
async def test_apply_stars_payment_rejects_wrong_amount(session: AsyncSession) -> None:
    tariffs = await list_active_tariffs(session)
    user = await upsert_user(session, telegram_id=9002, username="bad", full_name="Bad")
    order = await create_order(session, user, tariffs[0], payment_method="stars", stars_amount=75)
    settings = Settings(bot_token="1:TEST", stars_enabled=True, panel_enabled=False)
    fake = _FakeSession()
    bot = Bot(token=settings.bot_token, session=fake, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    result = await apply_stars_payment(
        session,
        bot,
        settings,
        user_id=user.telegram_id,
        currency=STARS_CURRENCY,
        total_amount=1,
        invoice_payload=encode_stars_payload(order_id=order.id, payment_code=order.payment_code),
        telegram_payment_charge_id="charge-wrong",
    )
    assert result is None
    await session.refresh(order)
    assert order.status == OrderStatus.awaiting_payment.value
    await bot.session.close()
