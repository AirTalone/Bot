#!/usr/bin/env python3
"""Живая проверка формулы курса: Rapira (+ CryptoCards из .env если есть)."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


async def main() -> int:
    _load_dotenv()
    from exchange.config import load_settings
    from exchange.rates.pricing import compute_client_quote
    from exchange.rates.sources import fetch_cryptocards_rate, fetch_rapira_usdt_rub

    settings = load_settings()
    rapira = None
    try:
        rapira = await fetch_rapira_usdt_rub(timeout_sec=settings.rate_timeout_sec)
        print(f"Rapira: {rapira:.4f}")
    except Exception as exc:
        print(f"Rapira FAIL: {exc}")
        print(f"Rapira fallback: {settings.usdt_rate_rub:.4f}")
        rapira = settings.usdt_rate_rub

    cc = None
    if settings.cryptocards_token or settings.cryptocards_authorization:
        try:
            cc = await fetch_cryptocards_rate(
                api_url=settings.cryptocards_api_url,
                authorization=settings.cryptocards_authorization,
                token=settings.cryptocards_token,
                ukey=settings.cryptocards_ukey,
                cookie=settings.cryptocards_cookie,
                rate_field=settings.cryptocards_rate_field,
                timeout_sec=settings.rate_timeout_sec,
            )
            print(f"CryptoCards: {cc:.4f}")
        except Exception as exc:
            print(f"CryptoCards FAIL: {exc}")
    else:
        cc = round(float(rapira) + 1.5, 4)
        print(f"CryptoCards: нет токена в .env — демо CC=Rapira+1.5 → {cc:.4f}")

    for label, amount in (
        ("15 000 ₽", 15_000),
        ("35 000 ₽", 35_000),
        ("50 000 ₽", 50_000),
    ):
        q = compute_client_quote(
            amount_rub=amount,
            rapira=rapira,
            cryptocards=cc,
            fallback_rate=settings.usdt_rate_rub,
            markup_rub=settings.markup_rub_default,
            cc_edge_percent=settings.cc_edge_percent,
            tier_30k=settings.amount_tier_30k,
            tier_40k=settings.amount_tier_40k,
            discount_30k=settings.amount_discount_30k,
            discount_40k=settings.amount_discount_40k,
            min_margin_percent=settings.min_margin_percent,
            min_margin_percent_40k=settings.min_margin_percent_40k,
        )
        print(
            f"{label}: курс={q.suggested_rate:.4f} · "
            f"себест.={q.effective_cost} · маржа={q.margin_percent}% · "
            f"мин={q.min_margin_percent}% · ok={q.margin_ok} · {q.formula}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
