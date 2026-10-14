import secrets
from io import BytesIO

import qrcode

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 6


def new_payment_code() -> str:
    body = "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))
    return f"VPN-{body}"


def format_money(price_minor: int) -> str:
    sign = "-" if price_minor < 0 else ""
    rubles, kopecks = divmod(abs(price_minor), 100)
    rubles_text = f"{rubles:,}".replace(",", " ")
    if kopecks:
        return f"{sign}{rubles_text},{kopecks:02d} ₽"
    return f"{sign}{rubles_text} ₽"


def build_qr_payload(
    *,
    payment_title: str,
    payment_details: str,
    static_payload: str,
    amount: str,
    payment_code: str,
) -> str:
    static = static_payload.strip()
    if static:
        return static
    title = payment_title.strip() or "Оплата VPN"
    return "\n".join(
        [
            title,
            payment_details.strip(),
            f"Сумма: {amount}",
            f"Код: {payment_code}",
        ]
    )


def is_access_link(value: str) -> bool:
    text = value.strip()
    if len(text) < 8 or len(text) > 2000:
        return False
    if any(character.isspace() for character in text):
        return False
    return "://" in text


def render_qr_png(payload: str) -> bytes:
    code = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    code.add_data(payload)
    code.make(fit=True)
    image = code.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
