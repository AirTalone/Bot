"""Хранение семплов курса за сутки (среднее как у CryptoCards)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import aiosqlite

MOSCOW = ZoneInfo("Europe/Moscow")

SCHEMA = """
CREATE TABLE IF NOT EXISTS rate_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    price REAL NOT NULL,
    day_key TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rate_samples_day
    ON rate_samples(source, day_key);
"""


def moscow_day_key(now: datetime | None = None) -> str:
    now = now or datetime.now(MOSCOW)
    if now.tzinfo is None:
        now = now.replace(tzinfo=MOSCOW)
    return now.astimezone(MOSCOW).strftime("%Y-%m-%d")


class RateSampleStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("RateSampleStore is not connected")
        return self._conn

    async def add_sample(self, *, source: str, price: float) -> None:
        day = moscow_day_key()
        now = datetime.now(MOSCOW).isoformat()
        await self.conn.execute(
            "INSERT INTO rate_samples(source, price, day_key, created_at) VALUES (?, ?, ?, ?)",
            (source, price, day, now),
        )
        await self.conn.commit()

    async def day_average(self, source: str) -> tuple[float | None, int]:
        day = moscow_day_key()
        cursor = await self.conn.execute(
            "SELECT AVG(price), COUNT(*) FROM rate_samples WHERE source = ? AND day_key = ?",
            (source, day),
        )
        row = await cursor.fetchone()
        if not row or not row[1]:
            return None, 0
        return float(row[0]), int(row[1])
