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

    auth = (authorization or "").strip().strip('"').strip("'")
    if auth.lower().startswith("authorization:"):
        auth = auth.split(":", 1)[1].strip()
    cookie = (cookie or "").strip().strip('"').strip("'")
    if cookie.lower().startswith("cookie:"):
        cookie = cookie.split(":", 1)[1].strip()

    auth_candidates: list[str] = []
    if auth:
        auth_candidates.append(auth)
        if not auth.lower().startswith("bearer "):
            auth_candidates.append(f"Bearer {auth}")

    if not auth_candidates and not cookie:
        raise RuntimeError("CryptoCards: пустой Authorization/Cookie")

    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    last_status = None
    last_text = ""
    payload: Any = None

    async with aiohttp.ClientSession(timeout=timeout) as session:
        # Сначала пробуем Authorization (как есть и с Bearer), затем Cookie.
        attempts: list[dict[str, str]] = []
        for candidate in auth_candidates:
            attempts.append({"Authorization": candidate})
        if cookie:
            attempts.append({"Cookie": cookie})
        if not attempts:
            attempts.append({})

        for extra in attempts:
            headers = {"Accept": "application/json", **extra}
            async with session.get(api_url, headers=headers) as resp:
                text = await resp.text()
                last_status = resp.status
                last_text = text[:200]
                if resp.status >= 400:
                    continue
                try:
                    payload = await resp.json(content_type=None)
                except Exception as exc:
                    raise RuntimeError(f"CryptoCards: invalid JSON ({exc})") from exc
                break
        else:
            raise RuntimeError(
                f"CryptoCards HTTP {last_status}: {last_text} "
                "(проверь CRYPTOCARDS_AUTHORIZATION из Dolphin → account → Headers)"
            )

    rate = _extract_rate_field(payload, rate_field)
    if rate is None:
        raise RuntimeError(f"CryptoCards: field '{rate_field}' not found in response")
    return rate
