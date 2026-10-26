"""Генерация QR-кода в стиле СБП (НСПК)."""

from __future__ import annotations

import io
from urllib.parse import urlparse

import qrcode
from PIL import Image, ImageDraw

# Официальный цвет QR СБП по гайдлайну НСПК
SBP_PURPLE = (0x1D, 0x13, 0x46)
WHITE = (255, 255, 255)
# Фон «карточки» как на типичных скринах оплаты (чтобы в Telegram не было чёрных углов)
CARD_BACKDROP = (0x2B, 0x2A, 0x35)


def is_plausible_url(text: str) -> bool:
    """Проверяет, что текст похож на ссылку (http/https или без схемы)."""
    text = text.strip()
    if not text or any(ch.isspace() for ch in text):
        return False
    if "://" not in text:
        text = "https://" + text
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    host = parsed.netloc
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    # хотя бы домен вида a.b или IP / localhost
    return ("." in host) or host.startswith("localhost") or host.replace(":", "").isdigit()


def normalize_url(text: str) -> str:
    text = text.strip()
    if "://" not in text:
        return "https://" + text
    return text


def _round_corners(img: Image.Image, radius: int) -> Image.Image:
    """Скругляет углы (снаружи — прозрачность)."""
    if radius <= 0:
        return img.convert("RGBA")

    img = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=radius, fill=255)

    result = Image.new("RGBA", img.size, (0, 0, 0, 0))
    result.paste(img, (0, 0), mask=mask)
    return result


def generate_sbp_qr(
    data: str,
    *,
    box_size: int = 14,
    border: int = 3,
    corner_radius: int = 72,
    padding: int = 36,
    fill_color: tuple[int, int, int] = SBP_PURPLE,
    back_color: tuple[int, int, int] = WHITE,
    backdrop_color: tuple[int, int, int] = CARD_BACKDROP,
) -> bytes:
    """
    PNG QR в фирменном стиле СБП:
    фиолетовые модули (#1d1346) на белой скруглённой карточке,
    карточка на тёмном фоне (удобно для Telegram).
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)

    qr_img = qr.make_image(fill_color=fill_color, back_color=back_color).convert("RGB")
    rounded = _round_corners(qr_img, corner_radius)

    canvas_size = (rounded.width + padding * 2, rounded.height + padding * 2)
    canvas = Image.new("RGB", canvas_size, backdrop_color)
    canvas.paste(rounded, (padding, padding), rounded)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def generate_sbp_qr_file(data: str, **kwargs) -> io.BytesIO:
    """То же, что generate_sbp_qr, но BytesIO для отправки в Telegram."""
    png = generate_sbp_qr(data, **kwargs)
    bio = io.BytesIO(png)
    bio.name = "qr.png"
    bio.seek(0)
    return bio
