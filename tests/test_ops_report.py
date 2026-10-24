from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.admin_ops import record_audit
from bot.services.ops_report import collect_weekly_report
from bot.services.orders import create_order, fulfill_order, list_active_tariffs, mark_paid, upsert_user
from bot.texts import weekly_ops_report_text


@pytest.mark.asyncio
async def test_weekly_ops_report(session: AsyncSession) -> None:
    tariffs = await list_active_tariffs(session)
    user = await upsert_user(session, telegram_id=8801, username="ops", full_name="Ops")
    order = await create_order(session, user, tariffs[0])
    claimed = await mark_paid(session, order.id, user.id)
    assert claimed is not None
    fulfilled = await fulfill_order(
        session,
        claimed.id,
        "https://panel.test/sub/ops",
        expires_at=datetime.now(UTC) + timedelta(days=20),
    )
    assert fulfilled is not None
    await record_audit(session, admin_telegram_id=1, action="panel_error", detail="x", order_id=fulfilled.id)

    report = await collect_weekly_report(session, window_days=7)
    assert report.fulfilled_count >= 1
    assert report.revenue_minor >= tariffs[0].price_minor
    assert report.active_subs >= 1
    assert report.panel_errors >= 1
    assert report.approx_mrr_minor >= tariffs[0].price_minor
    body = weekly_ops_report_text(report)
    assert "Approx MRR" in body
    assert "Churn proxy" in body


@pytest.mark.asyncio
async def test_churn_proxy_counts_expired(session: AsyncSession) -> None:
    tariffs = await list_active_tariffs(session)
    user = await upsert_user(session, telegram_id=8802, username="churn", full_name="Churn")
    order = await create_order(session, user, tariffs[0])
    claimed = await mark_paid(session, order.id, user.id)
    assert claimed is not None
    await fulfill_order(
        session,
        claimed.id,
        "https://panel.test/sub/churn",
        expires_at=datetime.now(UTC) - timedelta(hours=2),
    )
    report = await collect_weekly_report(session, window_days=7)
    assert report.expired_count >= 1
    assert report.churn_proxy_pct > 0
