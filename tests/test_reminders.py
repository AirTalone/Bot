from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import OrderStatus
from bot.services.orders import create_order, fulfill_order, list_active_tariffs, mark_paid, upsert_user
from bot.services.reminders import list_due_expired, list_due_reminders, mark_reminder_sent
from bot.texts import faq_text, help_text, orders_text


@pytest.mark.asyncio
async def test_list_due_reminders(session: AsyncSession) -> None:
    tariffs = await list_active_tariffs(session)
    user = await upsert_user(session, telegram_id=501, username="r", full_name="Rem")
    order = await create_order(session, user, tariffs[0])
    claimed = await mark_paid(session, order.id, user.id)
    assert claimed is not None
    soon = datetime.now(UTC) + timedelta(days=2)
    fulfilled = await fulfill_order(session, claimed.id, "https://panel.test/sub/x", expires_at=soon)
    assert fulfilled is not None

    due = await list_due_reminders(session, days_before=3)
    assert any(item.id == fulfilled.id for item in due)

    await mark_reminder_sent(session, fulfilled.id)
    await session.commit()
    due_again = await list_due_reminders(session, days_before=3)
    assert all(item.id != fulfilled.id for item in due_again)


@pytest.mark.asyncio
async def test_list_due_expired(session: AsyncSession) -> None:
    tariffs = await list_active_tariffs(session)
    user = await upsert_user(session, telegram_id=502, username="e", full_name="Exp")
    order = await create_order(session, user, tariffs[0])
    claimed = await mark_paid(session, order.id, user.id)
    assert claimed is not None
    past = datetime.now(UTC) - timedelta(hours=1)
    fulfilled = await fulfill_order(session, claimed.id, "https://panel.test/sub/y", expires_at=past)
    assert fulfilled is not None

    due = await list_due_expired(session)
    assert any(item.id == fulfilled.id for item in due)


def test_help_and_faq_texts() -> None:
    help_body = help_text(support_contact="@support")
    assert "Streisand" in help_body or "Hiddify" in help_body
    assert "@support" in help_body
    faq_body = faq_text(support_contact="@support")
    assert "VPN-" in faq_body


@pytest.mark.asyncio
async def test_orders_text_shows_expiry(session: AsyncSession) -> None:
    tariffs = await list_active_tariffs(session)
    user = await upsert_user(session, telegram_id=503, username="o", full_name="Ord")
    order = await create_order(session, user, tariffs[0])
    claimed = await mark_paid(session, order.id, user.id)
    assert claimed is not None
    expires = datetime.now(UTC) + timedelta(days=10)
    fulfilled = await fulfill_order(
        session,
        claimed.id,
        "https://panel.test/sub/z",
        expires_at=expires,
    )
    assert fulfilled is not None
    text = orders_text([fulfilled])
    assert fulfilled.payment_code in text
    assert "до " in text
    assert fulfilled.status == OrderStatus.fulfilled
