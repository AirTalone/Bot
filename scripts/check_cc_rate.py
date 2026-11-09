#!/usr/bin/env python3
"""
Проверка формулы CryptoCards без логина:

  20-е объявление Bybit P2P (Сбер) ≈ курс в кабинете CC?

Запуск на VPS (из папки бота, с активированным venv):

  python scripts/check_cc_rate.py
  python scripts/check_cc_rate.py --side 0
  python scripts/check_cc_rate.py --index 20 --payment 585
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from exchange.rates.bybit_p2p import fetch_bybit_p2p_items  # noqa: E402
from exchange.rates.sources import fetch_rapira_usdt_rub  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--side", default="1", help="Bybit side: 0 или 1")
    parser.add_argument("--payment", default="585", help="ID оплаты Сбер в Bybit")
    parser.add_argument("--index", type=int, default=20, help="Номер объявления (1-based)")
    parser.add_argument("--amount", default="", help="Фильтр суммы, например 100000")
    args = parser.parse_args()

    print("=== Rapira USDT/RUB ===")
    try:
        rapira = await fetch_rapira_usdt_rub()
        print(f"Rapira: {rapira:.4f}")
    except Exception as exc:
        print(f"Rapira ERROR: {exc}")
        rapira = None

    print()
    print(
        f"=== Bybit P2P USDT/RUB · payment={args.payment} · side={args.side} "
        f"· amount={args.amount or '—'} ==="
    )
    try:
        items = await fetch_bybit_p2p_items(
            side=args.side,
            payment_id=args.payment,
            size=max(args.index + 5, 30),
            amount=args.amount,
        )
    except Exception as exc:
        print(f"Bybit ERROR: {exc}")
        return

    print(f"Объявлений получено: {len(items)}")
    if not items:
        print(
            "Пусто. Попробуй --side 0 или другой --payment / --amount.\n"
            "Важно: запускай на своём VPS (из облака Bybit часто режет)."
        )
        return

    show = min(len(items), max(args.index, 25))
    print()
    print("Первые объявления (номер · цена · ник):")
    for i in range(show):
        it = items[i]
        mark = "  <<<< 20-е" if i + 1 == args.index else ""
        nick = str(it.get("nickName") or "")[:24]
        print(f"  {i + 1:2d}. {float(it['price']):8.4f}  {nick}{mark}")

    if len(items) >= args.index:
        nth = float(items[args.index - 1]["price"])
        print()
        print(f"Итого #{args.index}: {nth:.4f} ₽/USDT")
        print()
        print("Сверь с курсом в кабинете CryptoCards прямо сейчас.")
        print("Если совпадает (±0.05–0.20) — формула саппорта верная.")
        if rapira is not None:
            print(f"Разница с Rapira: {nth - rapira:+.4f}")
    else:
        print(
            f"\nНужно минимум {args.index} объявлений, есть только {len(items)}."
        )


if __name__ == "__main__":
    asyncio.run(main())
