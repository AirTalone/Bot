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
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    else:
        options["pool_pre_ping"] = True
    return create_async_engine(database_url, **options)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    """Create tables from models. Used by tests and local SQLite quickstart."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def init_db(engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Test/local helper: create schema + seed tariffs."""
    from bot.services.orders import seed_tariffs

    await create_schema(engine)
    async with session_factory() as session:
        await seed_tariffs(session)
        await session.commit()


async def prepare_runtime_db(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    database_url: str,
    auto_create_sqlite: bool = True,
) -> None:
    """
    Runtime bootstrap for the bot process.

    Postgres/MySQL: schema comes from Alembic (migrate service).
    SQLite: optionally create tables so `python -m bot` works without alembic.
    Always seeds tariffs idempotently.
    """
    from bot.services.orders import seed_tariffs

    if auto_create_sqlite and database_url.startswith("sqlite"):
        await create_schema(engine)
    async with session_factory() as session:
        await seed_tariffs(session)
        await session.commit()
