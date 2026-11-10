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
    _describe_secret(settings.cryptocards_token, "x-token (CRYPTOCARDS_TOKEN)")
    _describe_secret(settings.cryptocards_ukey, "x-ukey (CRYPTOCARDS_UKEY)")
    _describe_secret(settings.cryptocards_authorization, "Authorization (legacy)")
    _describe_secret(settings.cryptocards_cookie, "Cookie")
    try:
        rate = await fetch_cryptocards_rate(
            api_url=settings.cryptocards_api_url,
            authorization=settings.cryptocards_authorization,
            token=settings.cryptocards_token,
            ukey=settings.cryptocards_ukey,
            cookie=settings.cryptocards_cookie,
            rate_field=settings.cryptocards_rate_field,
        )
        print(f"OK CryptoCards rate = {rate:.4f}")
    except Exception as exc:
        print("FAIL:", exc)
        print(
            "Нужно в Dolphin → F12 → Application → Local Storage:\n"
            "  token  → CRYPTOCARDS_TOKEN=...\n"
            "  ukey   → CRYPTOCARDS_UKEY=...\n"
            "Без слова Bearer. Это не Authorization."
        )
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
