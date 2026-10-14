from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import OrderStatus, Tariff
from bot.services.orders import (
    TARIFF_SEED,
    cancel_awaiting,
    count_orders,
    create_order,
    fulfill_order,
    get_tariff,
    list_active_tariffs,
    list_pending,
    list_user_orders,
    mark_paid,
    reject_order,
    seed_tariffs,
    upsert_user,
)


async def test_seed_is_idempotent(session: AsyncSession) -> None:
    await seed_tariffs(session)
    tariffs = await list_active_tariffs(session)
    assert [tariff.slug for tariff in tariffs] == [item.slug for item in TARIFF_SEED]
    assert tariffs[0].price_minor == 19_900


async def test_checkout_claim_and_fulfill(session: AsyncSession) -> None:
    tariffs = await list_active_tariffs(session)
    user = await upsert_user(session, telegram_id=42, username="ivan", full_name="Иван")
    order = await create_order(session, user, tariffs[0])

    assert order.status == OrderStatus.awaiting_payment
    assert order.price_minor == tariffs[0].price_minor
    assert order.tariff_title == "1 месяц"

    claimed = await mark_paid(session, order.id, user.id)
    assert claimed is not None
    assert claimed.status == OrderStatus.pending_review
    assert claimed.claimed_at is not None
    assert await mark_paid(session, order.id, user.id) is None
    assert await count_orders(session, OrderStatus.pending_review) == 1
    assert len(await list_pending(session)) == 1

    fulfilled = await fulfill_order(session, order.id, "vless://uuid@host:443")
    assert fulfilled is not None
    assert fulfilled.status == OrderStatus.fulfilled
    assert fulfilled.access_link == "vless://uuid@host:443"
    assert await fulfill_order(session, order.id, "vless://again") is None

    stored = await list_user_orders(session, user.id)
    assert stored[0].access_link == "vless://uuid@host:443"


async def test_new_checkout_cancels_only_unpaid_order(session: AsyncSession) -> None:
    tariffs = await list_active_tariffs(session)
    user = await upsert_user(session, telegram_id=7, username=None, full_name="Анна")
    first = await create_order(session, user, tariffs[0])
    claimed = await mark_paid(session, first.id, user.id)
    assert claimed is not None

    second = await create_order(session, user, tariffs[1])
    third = await create_order(session, user, tariffs[2])

    orders = {order.payment_code: order.status for order in await list_user_orders(session, user.id)}
    assert orders[claimed.payment_code] == OrderStatus.pending_review
    assert orders[second.payment_code] == OrderStatus.cancelled
    assert orders[third.payment_code] == OrderStatus.awaiting_payment


async def test_buyer_cannot_claim_someone_elses_order(session: AsyncSession) -> None:
    tariff = await _first_tariff(session)
    owner = await upsert_user(session, telegram_id=1, username="owner", full_name="Owner")
    stranger = await upsert_user(session, telegram_id=2, username="stranger", full_name="Stranger")
    order = await create_order(session, owner, tariff)

    assert await mark_paid(session, order.id, stranger.id) is None
    assert await cancel_awaiting(session, order.id, stranger.id) is None
    cancelled = await cancel_awaiting(session, order.id, owner.id)
    assert cancelled is not None
    assert cancelled.status == OrderStatus.cancelled
    assert await mark_paid(session, order.id, owner.id) is None


async def test_reject_pending_order(session: AsyncSession) -> None:
    tariff = await _first_tariff(session)
    user = await upsert_user(session, telegram_id=9, username="u", full_name="User")
    order = await create_order(session, user, tariff)
    assert await reject_order(session, order.id) is None

    claimed = await mark_paid(session, order.id, user.id)
    assert claimed is not None
    rejected = await reject_order(session, order.id)
    assert rejected is not None
    assert rejected.status == OrderStatus.rejected
    assert await fulfill_order(session, order.id, "https://access.example/sub") is None


async def test_inactive_tariff_is_hidden(session: AsyncSession) -> None:
    tariff = await _first_tariff(session)
    tariff.is_active = False
    await session.flush()
    assert await get_tariff(session, tariff.id) is None


async def _first_tariff(session: AsyncSession) -> Tariff:
    tariffs = await list_active_tariffs(session)
    return tariffs[0]
