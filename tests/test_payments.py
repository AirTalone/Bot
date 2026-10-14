from datetime import datetime, timezone

from bot.callbacks import AdminOrderAction
from bot.keyboards import tariffs_keyboard
from bot.models import Order, OrderStatus, Tariff
from bot.services.payments import build_qr_payload, format_money, is_access_link, new_payment_code, render_qr_png
from bot.texts import payment_caption


def test_payment_code_shape() -> None:
    code = new_payment_code()
    assert code.startswith("VPN-")
    assert len(code) == 10
    assert all(character not in code for character in "01IO")


def test_format_money() -> None:
    assert format_money(19_900) == "199 ₽"
    assert format_money(19_950) == "199,50 ₽"
    assert format_money(1_990_000) == "19 900 ₽"


def test_qr_payload_includes_code_and_amount() -> None:
    payload = build_qr_payload(
        payment_title="Оплата VPN",
        payment_details="СБП +7 900",
        static_payload="  ",
        amount="199 ₽",
        payment_code="VPN-ABC234",
    )
    assert "VPN-ABC234" in payload
    assert "199 ₽" in payload
    assert "СБП +7 900" in payload


def test_static_qr_payload_is_used_as_is() -> None:
    payload = build_qr_payload(
        payment_title="Оплата VPN",
        payment_details="СБП",
        static_payload="https://pay.example/qr",
        amount="199 ₽",
        payment_code="VPN-ABC234",
    )
    assert payload == "https://pay.example/qr"


def test_render_qr_png() -> None:
    png = render_qr_png("VPN-ABC234")
    assert png.startswith(b"\x89PNG")


def test_access_link_rules() -> None:
    assert is_access_link("https://example.com/sub/abc")
    assert is_access_link("vless://uuid@host:443?type=tcp#node")
    assert not is_access_link("не ссылка")
    assert not is_access_link("https://example.com/a b")
    assert not is_access_link("")
    assert not is_access_link("https://example.com/" + ("a" * 2100))


def test_callback_data_fits_telegram_limit() -> None:
    packed = AdminOrderAction(order_id=1_000_000_000, action="confirm").pack()
    unpacked = AdminOrderAction.unpack(packed)
    assert unpacked.order_id == 1_000_000_000
    assert unpacked.action == "confirm"
    assert len(packed.encode()) <= 64


def test_tariff_button_and_caption() -> None:
    tariff = Tariff(id=1, slug="month_1", title="1 месяц", duration_days=30, price_minor=19_900, is_active=True)
    keyboard = tariffs_keyboard([tariff])
    assert keyboard.inline_keyboard[0][0].text == "1 месяц · 199 ₽"
    assert keyboard.inline_keyboard[1][0].text == "Мои заказы"

    order = Order(
        id=3,
        payment_code="VPN-ABC234",
        price_minor=19_900,
        tariff_title="1 месяц",
        duration_days=30,
        status=OrderStatus.awaiting_payment.value,
        created_at=datetime.now(timezone.utc),
    )
    caption = payment_caption(order, payment_details="СБП +7 900")
    assert "VPN-ABC234" in caption
    assert "199 ₽" in caption
    assert "СБП +7 900" in caption


def test_routers_load() -> None:
    from bot.handlers import admin_router, user_router

    assert admin_router.name == "admin"
    assert user_router.name == "user"
