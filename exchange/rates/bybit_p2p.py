"""
Эмуляция логики CryptoCards без логина:

«20-е объявление по направлению Сбер, средний показатель за сутки»
→ Bybit P2P USDT/RUB, payment=Sberbank (585), берём N-е объявление,
  копим семплы и считаем среднее за текущие сутки (Europe/Moscow).
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

BYBIT_P2P_URL = "https://api2.bybit.com/fiat/otc/item/online"
# Неофициальный id Сбера в Bybit P2P (из публичных интеграций)
DEFAULT_SBER_PAYMENT_ID = "585"


async def fetch_bybit_p2p_items(
    *,
    side: str = "1",
    payment_id: str = DEFAULT_SBER_PAYMENT_ID,
    size: int = 30,
    amount: str = "",
    timeout_sec: float = 20.0,
) -> list[dict[str, Any]]:
    body = {
        "userId": "",
        "tokenId": "USDT",
        "currencyId": "RUB",
        "payment": [str(payment_id)] if payment_id else [],
        "side": str(side),
        "size": str(max(size, 1)),
        "page": "1",
        "amount": amount or "",
        "authMaker": False,
        "canTrade": False,
        "itemRegion": 2,
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Origin": "https://www.bybit.com",
        "Referer": "https://www.bybit.com/fiat/trade/otc/USDT/RUB",
        "lang": "ru",
    }
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(BYBIT_P2P_URL, json=body, headers=headers) as resp:
            resp.raise_for_status()
            payload = await resp.json(content_type=None)

    if not isinstance(payload, dict):
        raise RuntimeError("Bybit P2P: unexpected response")
    if payload.get("ret_code") not in (0, "0", None):
        raise RuntimeError(
            f"Bybit P2P error: {payload.get('ret_code')} {payload.get('ret_msg')}"
        )
    items = (payload.get("result") or {}).get("items") or []
    if not isinstance(items, list):
        raise RuntimeError("Bybit P2P: items is not a list")
    return [x for x in items if isinstance(x, dict)]


async def fetch_nth_sber_ad_price(
    *,
    ad_index: int = 20,
    side: str = "1",
    payment_id: str = DEFAULT_SBER_PAYMENT_ID,
    amount: str = "",
    timeout_sec: float = 20.0,
) -> float:
    """
    ad_index — 1-based (20 = двадцатое объявление).
    """
    if ad_index < 1:
        raise ValueError("ad_index must be >= 1")
    items = await fetch_bybit_p2p_items(
        side=side,
        payment_id=payment_id,
        size=max(ad_index + 5, 25),
        amount=amount,
        timeout_sec=timeout_sec,
    )
    if len(items) < ad_index:
        raise RuntimeError(
            f"Bybit P2P: нужно ≥{ad_index} объявлений Сбер, пришло {len(items)}. "
            "Проверьте side/payment или IP сервера."
        )
    raw = items[ad_index - 1].get("price")
    price = float(raw)
    if price <= 0:
        raise RuntimeError("Bybit P2P: invalid price on N-th ad")
    return price
