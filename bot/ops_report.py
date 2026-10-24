"""CLI: print weekly ops report (for cron on the VPS)."""

from __future__ import annotations

import asyncio
import logging

from bot.config import get_settings
from bot.db import create_engine, create_session_factory, ensure_sqlite_parent
from bot.services.ops_report import collect_weekly_report
from bot.texts import weekly_ops_report_text


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    ensure_sqlite_parent(settings.database_url)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            report = await collect_weekly_report(session, window_days=7)
        # Strip HTML tags for plain cron logs.
        text = weekly_ops_report_text(report)
        plain = (
            text.replace("<b>", "")
            .replace("</b>", "")
            .replace("<code>", "")
            .replace("</code>", "")
        )
        print(plain)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
