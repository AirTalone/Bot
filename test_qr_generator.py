"""Простые проверки генератора (без Telegram)."""

from __future__ import annotations

import io
import unittest

from PIL import Image

from qr_generator import (
    SBP_PURPLE,
    generate_sbp_qr,
    is_plausible_url,
    normalize_url,
)

SAMPLE = "https://qr.nspk.ru/AD101055EDK5J0E099CQ1IGD7IAVBQK0"


class QrGeneratorTests(unittest.TestCase):
    def test_normalize_and_validate(self) -> None:
        self.assertTrue(is_plausible_url(SAMPLE))
        self.assertTrue(is_plausible_url("qr.nspk.ru/ABC"))
        self.assertFalse(is_plausible_url("not a url"))
        self.assertEqual(normalize_url("example.com/x"), "https://example.com/x")

    def test_png_looks_like_sbp_card(self) -> None:
        png = generate_sbp_qr(SAMPLE)
        self.assertGreater(len(png), 1000)

        img = Image.open(io.BytesIO(png))
        self.assertEqual(img.mode, "RGB")
        self.assertGreaterEqual(img.width, 400)
        self.assertEqual(img.width, img.height)

        # Уголок холста — тёмный backdrop, не белый
        corner = img.getpixel((0, 0))
        self.assertNotEqual(corner, (255, 255, 255))

        # Среди пикселей должен встречаться фирменный фиолетовый СБП
        pixels = img.getdata()
        self.assertIn(SBP_PURPLE, pixels)
        self.assertIn((255, 255, 255), pixels)


if __name__ == "__main__":
    unittest.main()
