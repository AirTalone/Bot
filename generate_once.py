"""Разовый генератор без Telegram: python generate_once.py <url> [out.png]"""

from __future__ import annotations

import sys

from qr_generator import generate_sbp_qr, is_plausible_url, normalize_url


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Использование:\n"
            "  python generate_once.py https://qr.nspk.ru/AD10... [qr.png]"
        )
        raise SystemExit(1)

    raw = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "qr.png"

    if not is_plausible_url(raw):
        raise SystemExit(f"Не похоже на ссылку: {raw}")

    url = normalize_url(raw)
    png = generate_sbp_qr(url)
    with open(out, "wb") as f:
        f.write(png)
    print(f"Сохранено: {out} ({len(png)} байт)")


if __name__ == "__main__":
    main()
