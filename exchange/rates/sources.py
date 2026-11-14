"""Источники курсов USDT/RUB."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

RAPIRA_URL = "https://api.rapira.net/open/market/rates"
RAPIRA_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _parse_rapira_usdt_rub(payload: Any) -> float:
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


async def _fetch_rapira_via_curl(*, timeout_sec: float) -> float:
    """Запасной путь: curl --http1.1 (aiohttp на части VPS ловит Server disconnected)."""
    curl = shutil.which("curl")
    if not curl:
        raise RuntimeError("curl not found")
    cmd = [
        curl,
        "--http1.1",
        "-fsS",
        "-m",
        str(max(3, int(timeout_sec))),
        "-A",
        RAPIRA_HEADERS["User-Agent"],
        "-H",
        "Accept: application/json",
        "-H",
        "Connection: close",
        RAPIRA_URL,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"curl exit {proc.returncode}: {(stderr or b'').decode(errors='replace')[:200]}"
        )
    payload = json.loads(stdout.decode())
    return _parse_rapira_usdt_rub(payload)


async def fetch_rapira_usdt_rub(*, timeout_sec: float = 15.0) -> float:
    """Публичный курс Rapira USDT/RUB (ask/close)."""
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            # Новый connector на каждую попытку: иначе после закрытия session
            # получаем "Session is closed". HTTP/1.1 + browser UA стабильнее к Rapira.
            connector = aiohttp.TCPConnector(
                force_close=True,
                enable_cleanup_closed=True,
            )
            async with aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers=RAPIRA_HEADERS,
                version=aiohttp.HttpVersion11,
            ) as session:
                async with session.get(RAPIRA_URL, headers=RAPIRA_HEADERS) as resp:
                    resp.raise_for_status()
                    payload = await resp.json(content_type=None)
            return _parse_rapira_usdt_rub(payload)
        except Exception as exc:
            last_error = exc
            logger.warning("Rapira aiohttp attempt %s failed: %s", attempt + 1, exc)
            await asyncio.sleep(0.4 * (attempt + 1))
            # После пары сетевых обрывов пробуем curl.
            if attempt >= 1:
                try:
                    rate = await _fetch_rapira_via_curl(timeout_sec=timeout_sec)
                    logger.info("Rapira fetched via curl fallback")
                    return rate
                except Exception as curl_exc:
                    last_error = curl_exc
                    logger.warning("Rapira curl fallback failed: %s", curl_exc)
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
