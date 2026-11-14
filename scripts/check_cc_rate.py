#!/usr/bin/env python3
"""
Проверка формулы CryptoCards / доступности Bybit+Rapira с VPS.

  python scripts/check_cc_rate.py
  python scripts/check_cc_rate.py --diagnose
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


async def show_list(side: str, payment: str, amount: str, index: int) -> bool:
    print(
        f"\n=== Bybit P2P · payment={payment} · side={side} · amount={amount or '—'} ==="
    )
    try:
        items = await fetch_bybit_p2p_items(
            side=side,
            payment_id=payment,
            size=max(index + 5, 30),
            amount=amount,
        )
    except Exception as exc:
        print(f"Bybit ERROR: {exc}")
        return False

    print(f"Объявлений получено: {len(items)}")
    if not items:
        return False

    show = min(len(items), max(index, 25))
    for i in range(show):
        it = items[i]
        mark = "  <<<< целевое" if i + 1 == index else ""
        nick = str(it.get("nickName") or "")[:24]
        print(f"  {i + 1:2d}. {float(it['price']):8.4f}  {nick}{mark}")

    if len(items) >= index:
        nth = float(items[index - 1]["price"])
        print(f"\nИтого #{index}: {nth:.4f} ₽/USDT")
        print("Сверь с курсом в кабинете CryptoCards прямо сейчас.")
        return True
    print(f"Мало объявлений: нужно ≥{index}, есть {len(items)}")
    return False


async def diagnose(index: int) -> None:
    print("=== Диагностика Bybit (несколько вариантов) ===")
    payments = ["585", "582", "581", ""]
    sides = ["1", "0"]
    amounts = ["", "10000", "50000", "100000"]
    found = False
    for payment in payments:
        for side in sides:
            for amount in amounts:
                label_pay = payment or "ANY"
                try:
                    items = await fetch_bybit_p2p_items(
                        side=side,
                        payment_id=payment,
                        size=30,
                        amount=amount,
                    )
                except Exception as exc:
                    print(f"pay={label_pay} side={side} amount={amount or '—'} ERR {exc}")
                    continue
                n = len(items)
                preview = ""
                if n:
                    preview = ", ".join(f"{float(x['price']):.2f}" for x in items[:3])
                    found = True
                print(
                    f"pay={label_pay} side={side} amount={amount or '—'} -> n={n}"
                    + (f" first={preview}" if preview else "")
                )
                if n >= index:
                    print(
                        f"  OK candidate: #{index} = {float(items[index - 1]['price']):.4f}"
                    )
                    return
    if not found:
        print(
            "\nВывод: с этого IP Bybit P2P не отдаёт объявления.\n"
            "Автопарсинг CC-формулы с сервера сейчас невозможен.\n"
            "Варианты:\n"
            "  1) сверить вручную в браузере Bybit ↔ CryptoCards\n"
            "  2) взять курс из CryptoCards /api/account с Authorization\n"
            "  3) поставить прокси/другой IP, который Bybit не режет"
        )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--side", default="1")
    parser.add_argument("--payment", default="585")
    parser.add_argument("--index", type=int, default=20)
    parser.add_argument("--amount", default="")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="перебрать side/payment/amount",
    )
    args = parser.parse_args()

    print("=== Rapira USDT/RUB ===")
    try:
        rapira = await fetch_rapira_usdt_rub()
        print(f"Rapira: {rapira:.4f}")
    except Exception as exc:
        print(f"Rapira ERROR: {exc}")

    if args.diagnose:
        await diagnose(args.index)
        return

    ok = await show_list(args.side, args.payment, args.amount, args.index)
    if not ok:
        print("\nПробую side=0 ...")
        ok = await show_list("0", args.payment, args.amount, args.index)
    if not ok:
        print("\nПусто. Запусти диагностику:")
        print("  .venv/bin/python scripts/check_cc_rate.py --diagnose")


if __name__ == "__main__":
    asyncio.run(main())
