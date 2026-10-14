from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from bot.models import Base


def ensure_sqlite_parent(database_url: str) -> None:
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        return
    path = database_url.removeprefix(prefix)
    if path in {":memory:", ""} or path.startswith("file:"):
        return
    parent = Path(path).parent
    if str(parent) not in {"", "."}:
        parent.mkdir(parents=True, exist_ok=True)


def create_engine(database_url: str) -> AsyncEngine:
    options: dict[str, object] = {}
    if not database_url.startswith("sqlite"):
        options["pool_pre_ping"] = True
    return create_async_engine(database_url, **options)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]) -> None:
    from bot.services.orders import seed_tariffs

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        await seed_tariffs(session)
        await session.commit()
