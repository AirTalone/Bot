"""Источники курсов USDT/RUB."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


async def fetch_rapira_usdt_rub(*, timeout_sec: float = 15.0) -> float:
    """Публичный курс Rapira USDT/RUB (ask/close)."""
    url = "https://api.rapira.net/open/market/rates"
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers={"Accept": "application/json"}) as resp:
            resp.raise_for_status()
            payload = await resp.json(content_type=None)

    items = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise RuntimeError("Rapira: unexpected response shape")

    for row in items:
        if not isinstance(row, dict):
            continue
        if row.get("symbol") != "USDT/RUB":
            continue
        for key in ("askPrice", "close", "bidPrice"):
            value = row.get(key)
            if value is None:
                continue
            rate = float(value)
            if rate > 0:
                return rate
    raise RuntimeError("Rapira: USDT/RUB not found")


def _extract_rate_field(payload: Any, field: str = "rate") -> float | None:
    if isinstance(payload, dict):
        if field in payload and payload[field] is not None:
            try:
                value = float(payload[field])
                if value > 0:
                    return value
            except (TypeError, ValueError):
                pass
        # иногда курс вложен: data.rate / account.rate
        for key in ("data", "account", "user", "result"):
            nested = payload.get(key)
            found = _extract_rate_field(nested, field)
            if found is not None:
                return found
    return None


async def fetch_cryptocards_rate(
    *,
    api_url: str,
    authorization: str = "",
    cookie: str = "",
    rate_field: str = "rate",
    timeout_sec: float = 15.0,
) -> float:
    """
    Курс из CryptoCards (обычно GET https://cryptocards.ws/api/account → rate).

    Нужна авторизация из DevTools → Headers:
      Authorization: ...   или   Cookie: ...
    """
    if not api_url:
        raise RuntimeError("CryptoCards API URL is empty")

    headers: dict[str, str] = {"Accept": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    if cookie:
        headers["Cookie"] = cookie

    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(api_url, headers=headers) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"CryptoCards HTTP {resp.status}: {text[:200]}")
            try:
                payload = await resp.json(content_type=None)
            except Exception as exc:
                raise RuntimeError(f"CryptoCards: invalid JSON ({exc})") from exc

    rate = _extract_rate_field(payload, rate_field)
    if rate is None:
        raise RuntimeError(f"CryptoCards: field '{rate_field}' not found in response")
    return rate
