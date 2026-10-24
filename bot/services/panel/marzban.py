from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from bot.services.panel.base import PanelError, ProvisionedAccess

logger = logging.getLogger(__name__)


class MarzbanClient:
    """Minimal async Marzban REST client for create/extend subscription users."""

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        proxies: dict[str, Any] | None = None,
        inbounds: dict[str, list[str]] | None = None,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._proxies = proxies if proxies is not None else {"vless": {}}
        self._inbounds = inbounds if inbounds is not None else {}
        self._token: str | None = None
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def ensure_subscription(
        self,
        *,
        username: str,
        duration_days: int,
        note: str = "",
    ) -> ProvisionedAccess:
        if duration_days < 1:
            raise PanelError("duration_days must be >= 1")
        await self._ensure_token()
        existing = await self._get_user(username)
        if existing is None:
            expire_at = datetime.now(UTC) + timedelta(days=duration_days)
            payload = {
                "username": username,
                "proxies": self._proxies,
                "inbounds": self._inbounds,
                "expire": int(expire_at.timestamp()),
                "data_limit": 0,
                "data_limit_reset_strategy": "no_reset",
                "status": "active",
                "note": note[:500],
            }
            data = await self._request("POST", "/api/user", json=payload)
            return self._to_access(data, created=True)

        expire_at = self._extend_expire(existing.get("expire"), duration_days)
        data = await self._request(
            "PUT",
            f"/api/user/{username}",
            json={
                "status": "active",
                "expire": int(expire_at.timestamp()),
                "note": note[:500] if note else None,
            },
        )
        return self._to_access(data, created=False)

    async def _ensure_token(self) -> None:
        if self._token:
            return
        response = await self._client.post(
            "/api/admin/token",
            data={"username": self._username, "password": self._password, "grant_type": "password"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code >= 400:
            raise PanelError(f"marzban auth failed: HTTP {response.status_code}")
        token = response.json().get("access_token")
        if not token:
            raise PanelError("marzban auth failed: empty access_token")
        self._token = str(token)

    async def _get_user(self, username: str) -> dict[str, Any] | None:
        response = await self._client.get(
            f"/api/user/{username}",
            headers=self._auth_headers(),
        )
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise PanelError(f"marzban get user failed: HTTP {response.status_code}: {response.text[:300]}")
        return response.json()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._client.request(method, path, headers=self._auth_headers(), **kwargs)
        if response.status_code == 401:
            self._token = None
            await self._ensure_token()
            response = await self._client.request(method, path, headers=self._auth_headers(), **kwargs)
        if response.status_code >= 400:
            raise PanelError(f"marzban {method} {path} failed: HTTP {response.status_code}: {response.text[:300]}")
        data = response.json()
        if not isinstance(data, dict):
            raise PanelError("marzban returned unexpected payload")
        return data

    def _auth_headers(self) -> dict[str, str]:
        if not self._token:
            raise PanelError("marzban token is missing")
        return {"Authorization": f"Bearer {self._token}"}

    @staticmethod
    def _extend_expire(current_expire: Any, duration_days: int) -> datetime:
        now = datetime.now(UTC)
        base = now
        if isinstance(current_expire, int) and current_expire > 0:
            current = datetime.fromtimestamp(current_expire, tz=UTC)
            if current > now:
                base = current
        return base + timedelta(days=duration_days)

    @staticmethod
    def _to_access(data: dict[str, Any], *, created: bool) -> ProvisionedAccess:
        username = str(data.get("username") or "")
        subscription_url = str(data.get("subscription_url") or "")
        if not username or not subscription_url:
            raise PanelError("marzban response missing username or subscription_url")
        expire_raw = data.get("expire")
        expires_at: datetime | None = None
        if isinstance(expire_raw, int) and expire_raw > 0:
            expires_at = datetime.fromtimestamp(expire_raw, tz=UTC)
        return ProvisionedAccess(
            username=username,
            subscription_url=subscription_url,
            expires_at=expires_at,
            created=created,
        )
