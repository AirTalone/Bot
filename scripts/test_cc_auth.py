#!/usr/bin/env python3
"""Проверка CRYPTOCARDS_* из .env без печати секрета."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from exchange.config import load_settings  # noqa: E402
from exchange.rates.sources import fetch_cryptocards_rate  # noqa: E402


def _describe_secret(value: str, label: str) -> None:
    raw = (value or "").strip()
    if not raw:
        print(f"{label}: нет")
        return
    print(f"{label}: да · длина={len(raw)} · начинается с={raw[:6]!r}...")


async def main() -> None:
    settings = load_settings()
    print("URL:", settings.cryptocards_api_url)
    print("CC_RATE_SOURCE:", settings.cc_rate_source)
    _describe_secret(settings.cryptocards_authorization, "Authorization")
    _describe_secret(settings.cryptocards_cookie, "Cookie")
    try:
        rate = await fetch_cryptocards_rate(
            api_url=settings.cryptocards_api_url,
            authorization=settings.cryptocards_authorization,
            cookie=settings.cryptocards_cookie,
            rate_field=settings.cryptocards_rate_field,
        )
        print(f"OK CryptoCards rate = {rate:.4f}")
    except Exception as exc:
        print("FAIL:", exc)
        print(
            "Подсказка: в Local Storage скопируй именно VALUE токена "
            "(не JSON целиком, если там объект). "
            "Либо в Network у account возьми полный Cookie из Request Headers."
        )
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
