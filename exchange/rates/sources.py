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
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            # Новый connector на каждую попытку: иначе после закрытия session
            # получаем "Session is closed".
            connector = aiohttp.TCPConnector(
                force_close=True, enable_cleanup_closed=True
            )
            async with aiohttp.ClientSession(
                timeout=timeout, connector=connector
            ) as session:
                async with session.get(
                    url, headers={"Accept": "application/json"}
                ) as resp:
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
        except Exception as exc:
            last_error = exc
            logger.warning("Rapira attempt %s failed: %s", attempt + 1, exc)
    raise RuntimeError(f"Rapira failed after retries: {last_error}")


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


def _normalize_cc_secret(raw: str, *, prefix_to_strip: str) -> str:
    value = (raw or "").strip().strip('"').strip("'")
    # Иногда из Local Storage копируют JSON целиком.
    if value.startswith("{") and value.endswith("}"):
        try:
            import json

            obj = json.loads(value)
            for key in ("token", "access_token", "accessToken", "jwt", "auth", "value"):
                if isinstance(obj, dict) and obj.get(key):
                    value = str(obj[key]).strip()
                    break
        except Exception:
            pass
    low = value.lower()
    if low.startswith(prefix_to_strip):
        value = value.split(":", 1)[1].strip()
    return value


async def fetch_cryptocards_rate(
    *,
    api_url: str,
    authorization: str = "",
    token: str = "",
    ukey: str = "",
    cookie: str = "",
    rate_field: str = "rate",
    timeout_sec: float = 15.0,
) -> float:
    """
    Курс из CryptoCards (GET https://cryptocards.ws/api/account → rate).

    Фронт CC шлёт заголовки:
      x-token = localStorage.token
      x-ukey  = localStorage.ukey
    """
    if not api_url:
        raise RuntimeError("CryptoCards API URL is empty")

    auth = _normalize_cc_secret(authorization, prefix_to_strip="authorization:")
    token = _normalize_cc_secret(token, prefix_to_strip="token:")
    ukey = _normalize_cc_secret(ukey, prefix_to_strip="ukey:")
    cookie = _normalize_cc_secret(cookie, prefix_to_strip="cookie:")

    if not token and auth:
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else auth

    if not token:
        raise RuntimeError(
            "CryptoCards: нет token. В Dolphin → Application → Local Storage "
            "скопируй ключ token в CRYPTOCARDS_TOKEN"
        )

    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    browser_headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://cryptocards.ws",
        "Referer": "https://cryptocards.ws/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        # Как в их main.*.js
        "x-token": token,
    }
    if ukey:
        browser_headers["x-ukey"] = ukey
    if cookie:
        browser_headers["Cookie"] = cookie

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(api_url, headers=browser_headers) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(
                    f"CryptoCards HTTP {resp.status}: {text[:200]} "
                    "(нужны Local Storage: token → CRYPTOCARDS_TOKEN и ukey → CRYPTOCARDS_UKEY)"
                )
            try:
                payload = await resp.json(content_type=None)
            except Exception as exc:
                raise RuntimeError(f"CryptoCards: invalid JSON ({exc})") from exc

    rate = _extract_rate_field(payload, rate_field)
    if rate is None:
        raise RuntimeError(f"CryptoCards: field '{rate_field}' not found in response")
    return rate
