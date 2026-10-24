import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from bot.db import create_session_factory, init_db
from bot.services.cooldowns import gate


@pytest.fixture(autouse=True)
def _clear_cooldowns() -> None:
    gate._last.clear()


@pytest.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    factory = create_session_factory(engine)
    await init_db(engine, factory)
    yield factory
    await engine.dispose()


@pytest.fixture
async def session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncSession:
    async with session_factory() as db_session:
        yield db_session
