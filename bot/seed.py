"""Seed reference data after migrations (safe to re-run)."""

from __future__ import annotations

import asyncio
import logging

from bot.config import get_settings
from bot.db import create_engine, create_session_factory, ensure_sqlite_parent
from bot.services.orders import seed_tariffs

logger = logging.getLogger(__name__)


async def seed() -> None:
    settings = get_settings()
    ensure_sqlite_parent(settings.database_url)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await seed_tariffs(session)
            await session.commit()
        logger.info("tariff seed complete")
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(seed())


if __name__ == "__main__":
    main()
