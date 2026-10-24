from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models import Order, OrderStatus, Tariff, User
from bot.services.payments import new_payment_code


@dataclass(frozen=True, slots=True)
class TariffSeed:
    slug: str
    title: str
    duration_days: int
    price_minor: int
    stars_price: int


TARIFF_SEED: tuple[TariffSeed, ...] = (
    TariffSeed("month_1", "1 месяц", 30, 19_900, 75),
    TariffSeed("month_3", "3 месяца", 90, 49_900, 180),
    TariffSeed("month_6", "6 месяцев", 180, 89_900, 300),
)


def utcnow() -> datetime:
    return datetime.now(UTC)


async def seed_tariffs(session: AsyncSession) -> None:
    by_slug = {tariff.slug: tariff for tariff in await session.scalars(select(Tariff))}
    for item in TARIFF_SEED:
        existing = by_slug.get(item.slug)
        if existing is None:
            session.add(
                Tariff(
                    slug=item.slug,
                    title=item.title,
                    duration_days=item.duration_days,
                    price_minor=item.price_minor,
                    stars_price=item.stars_price,
                    is_active=True,
                )
            )
            continue
        if existing.stars_price == 0 and item.stars_price > 0:
            existing.stars_price = item.stars_price
    await session.flush()


async def list_active_tariffs(session: AsyncSession) -> list[Tariff]:
    result = await session.scalars(
        select(Tariff).where(Tariff.is_active.is_(True)).order_by(Tariff.price_minor, Tariff.id)
    )
    return list(result)


async def get_tariff(session: AsyncSession, tariff_id: int) -> Tariff | None:
    tariff = await session.get(Tariff, tariff_id)
    if tariff is None or not tariff.is_active:
        return None
    return tariff


async def upsert_user(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None,
    full_name: str,
) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            full_name=full_name,
            created_at=utcnow(),
        )
        session.add(user)
    else:
        user.username = username
        user.full_name = full_name
    await session.flush()
    return user


async def _allocate_payment_code(session: AsyncSession) -> str:
    for _ in range(5):
        code = new_payment_code()
        exists = await session.scalar(select(Order.id).where(Order.payment_code == code))
        if exists is None:
            return code
    raise RuntimeError("failed to allocate a payment code")


async def create_order(
    session: AsyncSession,
    user: User,
    tariff: Tariff,
    *,
    payment_method: str = "qr",
    stars_amount: int | None = None,
) -> Order:
    now = utcnow()
    await session.execute(
        update(Order)
        .where(Order.user_id == user.id, Order.status == OrderStatus.awaiting_payment.value)
        .values(status=OrderStatus.cancelled.value, resolved_at=now)
        .execution_options(synchronize_session=False)
    )
    order = Order(
        user=user,
        tariff=tariff,
        payment_code=await _allocate_payment_code(session),
        price_minor=tariff.price_minor,
        tariff_title=tariff.title,
        duration_days=tariff.duration_days,
        status=OrderStatus.awaiting_payment.value,
        payment_method=payment_method,
        stars_amount=stars_amount,
        created_at=now,
    )
    session.add(order)
    await session.flush()
    return order


async def get_order(session: AsyncSession, order_id: int) -> Order | None:
    return await session.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.user), selectinload(Order.tariff))
        .execution_options(populate_existing=True)
    )


async def _transition(
    session: AsyncSession,
    order_id: int,
    *,
    from_status: OrderStatus,
    to_status: OrderStatus,
    user_id: int | None = None,
    extra_values: dict[str, object] | None = None,
) -> Order | None:
    values: dict[str, object] = {"status": to_status.value}
    if extra_values:
        values.update(extra_values)
    conditions = [Order.id == order_id, Order.status == from_status.value]
    if user_id is not None:
        conditions.append(Order.user_id == user_id)
    result = await session.execute(
        update(Order)
        .where(*conditions)
        .values(**values)
        .returning(Order.id)
        .execution_options(synchronize_session=False)
    )
    if result.scalar_one_or_none() is None:
        return None
    return await get_order(session, order_id)


async def mark_paid(
    session: AsyncSession,
    order_id: int,
    user_id: int,
    *,
    payment_method: str | None = None,
    stars_amount: int | None = None,
    telegram_payment_charge_id: str | None = None,
) -> Order | None:
    """Move the buyer's own checkout from awaiting payment to admin review."""
    extra: dict[str, object] = {"claimed_at": utcnow()}
    if payment_method is not None:
        extra["payment_method"] = payment_method
    if stars_amount is not None:
        extra["stars_amount"] = stars_amount
    if telegram_payment_charge_id is not None:
        extra["telegram_payment_charge_id"] = telegram_payment_charge_id
    return await _transition(
        session,
        order_id,
        from_status=OrderStatus.awaiting_payment,
        to_status=OrderStatus.pending_review,
        user_id=user_id,
        extra_values=extra,
    )


async def get_order_by_charge_id(session: AsyncSession, charge_id: str) -> Order | None:
    return await session.scalar(
        select(Order)
        .where(Order.telegram_payment_charge_id == charge_id)
        .options(selectinload(Order.user), selectinload(Order.tariff))
    )


async def set_order_payment_method(
    session: AsyncSession,
    order_id: int,
    user_id: int,
    *,
    payment_method: str,
    stars_amount: int | None = None,
) -> Order | None:
    result = await session.execute(
        update(Order)
        .where(
            Order.id == order_id,
            Order.user_id == user_id,
            Order.status == OrderStatus.awaiting_payment.value,
        )
        .values(payment_method=payment_method, stars_amount=stars_amount)
        .returning(Order.id)
        .execution_options(synchronize_session=False)
    )
    if result.scalar_one_or_none() is None:
        return None
    return await get_order(session, order_id)


async def cancel_awaiting(session: AsyncSession, order_id: int, user_id: int) -> Order | None:
    return await _transition(
        session,
        order_id,
        from_status=OrderStatus.awaiting_payment,
        to_status=OrderStatus.cancelled,
        user_id=user_id,
        extra_values={"resolved_at": utcnow()},
    )


async def fulfill_order(
    session: AsyncSession,
    order_id: int,
    access_link: str,
    *,
    panel_username: str | None = None,
    expires_at: datetime | None = None,
) -> Order | None:
    """Confirm a reviewed payment and store the access link."""
    extra: dict[str, object] = {
        "access_link": access_link,
        "resolved_at": utcnow(),
    }
    if panel_username is not None:
        extra["panel_username"] = panel_username
    if expires_at is not None:
        extra["expires_at"] = expires_at
    return await _transition(
        session,
        order_id,
        from_status=OrderStatus.pending_review,
        to_status=OrderStatus.fulfilled,
        extra_values=extra,
    )


async def reject_order(session: AsyncSession, order_id: int) -> Order | None:
    return await _transition(
        session,
        order_id,
        from_status=OrderStatus.pending_review,
        to_status=OrderStatus.rejected,
        extra_values={"resolved_at": utcnow()},
    )


async def list_pending(session: AsyncSession, *, limit: int = 10) -> list[Order]:
    result = await session.scalars(
        select(Order)
        .where(Order.status == OrderStatus.pending_review.value)
        .options(selectinload(Order.user), selectinload(Order.tariff))
        .order_by(Order.claimed_at.asc(), Order.id.asc())
        .execution_options(populate_existing=True)
        .limit(limit)
    )
    return list(result)


async def count_orders(session: AsyncSession, status: OrderStatus) -> int:
    value = await session.scalar(
        select(func.count()).select_from(Order).where(Order.status == status.value)
    )
    return int(value or 0)


async def list_user_orders(session: AsyncSession, user_id: int, *, limit: int = 10) -> list[Order]:
    result = await session.scalars(
        select(Order)
        .where(Order.user_id == user_id)
        .options(selectinload(Order.user), selectinload(Order.tariff))
        .order_by(Order.id.desc())
        .execution_options(populate_existing=True)
        .limit(limit)
    )
    return list(result)
