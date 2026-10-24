from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import OrderStatus
from bot.services.admin_ops import (
    collect_stats,
    is_maintenance,
    list_orders_for_export,
    orders_to_csv,
    record_audit,
    search_orders,
    set_maintenance,
)
from bot.services.orders import create_order, fulfill_order, list_active_tariffs, mark_paid, upsert_user
from bot.texts import admin_home_text, maintenance_user_text


@pytest.mark.asyncio
async def test_stats_and_maintenance(session: AsyncSession) -> None:
    assert await is_maintenance(session) is False
    tariffs = await list_active_tariffs(session)
    user = await upsert_user(session, telegram_id=701, username="a", full_name="A")
    order = await create_order(session, user, tariffs[0])
    claimed = await mark_paid(session, order.id, user.id)
    assert claimed is not None
    await fulfill_order(
        session,
        claimed.id,
        "https://panel.test/sub/a",
        expires_at=datetime.now(UTC) + timedelta(days=5),
    )
    await record_audit(session, admin_telegram_id=1, action="panel_error", detail="boom", order_id=claimed.id)

    stats = await collect_stats(session)
    assert stats.pending_review == 0
    assert stats.fulfilled_today >= 1
    assert stats.active_subs >= 1
    assert stats.panel_errors_today >= 1
    assert "На проверке" in admin_home_text(stats)

    await set_maintenance(session, True)
    assert await is_maintenance(session) is True
    assert "технические работы" in maintenance_user_text(support_contact="@s").lower()


@pytest.mark.asyncio
async def test_search_by_code_and_telegram_id(session: AsyncSession) -> None:
    tariffs = await list_active_tariffs(session)
    user = await upsert_user(session, telegram_id=702, username="findme", full_name="Find")
    order = await create_order(session, user, tariffs[0])
    by_code = await search_orders(session, order.payment_code)
    assert len(by_code) == 1
    assert by_code[0].id == order.id
    by_tg = await search_orders(session, "702")
    assert any(item.id == order.id for item in by_tg)
    by_user = await search_orders(session, "@findme")
    assert any(item.id == order.id for item in by_user)


@pytest.mark.asyncio
async def test_csv_export(session: AsyncSession) -> None:
    tariffs = await list_active_tariffs(session)
    user = await upsert_user(session, telegram_id=703, username="c", full_name="C")
    order = await create_order(session, user, tariffs[0])
    orders = await list_orders_for_export(session, days=30)
    assert any(item.id == order.id for item in orders)
    csv_body = orders_to_csv(orders)
    assert "payment_code" in csv_body
    assert order.payment_code in csv_body
    assert OrderStatus.awaiting_payment.value in csv_body
