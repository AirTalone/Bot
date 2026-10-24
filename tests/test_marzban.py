import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from bot.config import Settings
from bot.services.orders import create_order, list_active_tariffs, upsert_user
from bot.services.panel.factory import build_panel_client
from bot.services.panel.marzban import MarzbanClient
from bot.services.provisioning import panel_username_for_telegram, provision_and_fulfill
from sqlalchemy.ext.asyncio import AsyncSession


def _settings(**overrides: object) -> Settings:
    data = {
        "bot_token": "1:TEST",
        "panel_enabled": True,
        "panel_provider": "marzban",
        "panel_base_url": "https://panel.test",
        "panel_username": "admin",
        "panel_password": "secret",
        "panel_proxies_json": '{"vless": {}}',
        "panel_inbounds_json": "{}",
    }
    data.update(overrides)
    return Settings(**data)


@pytest.mark.asyncio
async def test_marzban_creates_user(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/admin/token":
            return httpx.Response(200, json={"access_token": "tok"})
        if request.method == "GET" and request.url.path == "/api/user/tg42":
            return httpx.Response(404, json={"detail": "User not found"})
        if request.method == "POST" and request.url.path == "/api/user":
            body = json.loads(request.content.decode())
            assert body["username"] == "tg42"
            assert body["proxies"] == {"vless": {}}
            expire = body["expire"]
            return httpx.Response(
                200,
                json={
                    "username": "tg42",
                    "subscription_url": "https://panel.test/sub/abc",
                    "expire": expire,
                },
            )
        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)
    client = MarzbanClient(
        base_url="https://panel.test",
        username="admin",
        password="secret",
        transport=transport,
    )
    access = await client.ensure_subscription(username="tg42", duration_days=30, note="order:1")
    await client.aclose()
    assert access.created is True
    assert access.subscription_url == "https://panel.test/sub/abc"
    assert access.expires_at is not None
    assert ("POST", "/api/admin/token") in calls
    assert ("POST", "/api/user") in calls


@pytest.mark.asyncio
async def test_marzban_extends_existing_user() -> None:
    current_expire = int((datetime.now(UTC) + timedelta(days=5)).timestamp())

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/admin/token":
            return httpx.Response(200, json={"access_token": "tok"})
        if request.method == "GET" and request.url.path == "/api/user/tg7":
            return httpx.Response(
                200,
                json={
                    "username": "tg7",
                    "subscription_url": "https://panel.test/sub/old",
                    "expire": current_expire,
                },
            )
        if request.method == "PUT" and request.url.path == "/api/user/tg7":
            body = json.loads(request.content.decode())
            assert body["expire"] >= current_expire + 29 * 86400
            return httpx.Response(
                200,
                json={
                    "username": "tg7",
                    "subscription_url": "https://panel.test/sub/new",
                    "expire": body["expire"],
                },
            )
        return httpx.Response(500, text="unexpected")

    client = MarzbanClient(
        base_url="https://panel.test",
        username="admin",
        password="secret",
        transport=httpx.MockTransport(handler),
    )
    access = await client.ensure_subscription(username="tg7", duration_days=30)
    await client.aclose()
    assert access.created is False
    assert access.subscription_url == "https://panel.test/sub/new"


def test_build_panel_client_disabled() -> None:
    assert build_panel_client(_settings(panel_enabled=False)) is None


def test_panel_username() -> None:
    assert panel_username_for_telegram(42) == "tg42"


@pytest.mark.asyncio
async def test_provision_and_fulfill(session: AsyncSession) -> None:
    tariffs = await list_active_tariffs(session)
    user = await upsert_user(session, telegram_id=99, username="u", full_name="User")
    order = await create_order(session, user, tariffs[0])
    from bot.services.orders import mark_paid

    claimed = await mark_paid(session, order.id, user.id)
    assert claimed is not None

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/admin/token":
            return httpx.Response(200, json={"access_token": "tok"})
        if request.method == "GET":
            return httpx.Response(404, json={"detail": "missing"})
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "username": "tg99",
                    "subscription_url": "https://panel.test/sub/zz",
                    "expire": int((datetime.now(UTC) + timedelta(days=30)).timestamp()),
                },
            )
        return httpx.Response(500, text="no")

    panel = MarzbanClient(
        base_url="https://panel.test",
        username="admin",
        password="secret",
        transport=httpx.MockTransport(handler),
    )
    fulfilled = await provision_and_fulfill(session, claimed, panel)
    await panel.aclose()
    assert fulfilled.status == "fulfilled"
    assert fulfilled.access_link == "https://panel.test/sub/zz"
    assert fulfilled.panel_username == "tg99"
    assert fulfilled.expires_at is not None
