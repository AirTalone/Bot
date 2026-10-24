import asyncio
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.db import create_session_factory, init_db
from bot.services.orders import create_order, get_tariff, list_active_tariffs, upsert_user


@pytest.mark.asyncio
async def test_100_parallel_create_orders(tmp_path: Path) -> None:
    db_path = tmp_path / "load.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    await init_db(engine, session_factory)

    async with session_factory() as session:
        tariffs = await list_active_tariffs(session)
        tariff_id = tariffs[0].id
        await session.commit()

    sem = asyncio.Semaphore(25)

    async def one(telegram_id: int) -> int:
        async with sem:
            async with session_factory() as session:
                user = await upsert_user(
                    session,
                    telegram_id=telegram_id,
                    username=f"u{telegram_id}",
                    full_name=f"User {telegram_id}",
                )
                tariff = await get_tariff(session, tariff_id)
                assert tariff is not None
                order = await create_order(session, user, tariff)
                await session.commit()
                return order.id

    try:
        ids = await asyncio.gather(*[one(10_000 + i) for i in range(100)])
        assert len(ids) == 100
        assert len(set(ids)) == 100
    finally:
        await engine.dispose()
