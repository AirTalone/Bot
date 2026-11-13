"""SQLite-хранилище заявок (aiosqlite)."""

from __future__ import annotations

import json
import secrets
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import aiosqlite

from exchange.models import Order, Requisites, iso, parse_dt, utcnow
from exchange.statuses import OrderStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id TEXT NOT NULL UNIQUE,
    client_tg_id INTEGER NOT NULL,
    client_username TEXT,
    amount_rub REAL NOT NULL,
    amount_usdt REAL NOT NULL,
    rate REAL NOT NULL,
    usdt_address TEXT NOT NULL,
    status TEXT NOT NULL,
    requisites_bank TEXT,
    requisites_detail TEXT,
    requisites_holder TEXT,
    requisites_sbp_url TEXT,
    requisites_by INTEGER,
    requisites_at TEXT,
    payment_deadline_at TEXT,
    receipt_file_id TEXT,
    receipt_file_unique_id TEXT,
    receipt_check_status TEXT,
    receipt_check_message TEXT,
    receipt_check_raw TEXT,
    support_reviewed_by INTEGER,
    support_reviewed_at TEXT,
    support_note TEXT,
    payout_txid TEXT,
    payout_by INTEGER,
    payout_at TEXT,
    cancel_reason TEXT,
    extra_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_client ON orders(client_tg_id);
CREATE INDEX IF NOT EXISTS idx_orders_deadline ON orders(payment_deadline_at);

-- Карточка заявки в рабочей группе сотрудников (одно сообщение на заявку)
CREATE TABLE IF NOT EXISTS staff_cards (
    order_id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    status TEXT NOT NULL
);

-- Кто из сотрудников ведёт заявку (кнопка «Взять»)
CREATE TABLE IF NOT EXISTS order_owners (
    order_id INTEGER PRIMARY KEY,
    tg_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    taken_at TEXT NOT NULL
);
"""


def _new_public_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(6))
    return f"EX-{body}"


def _row_to_order(row: aiosqlite.Row) -> Order:
    extra_raw = row["extra_json"] or "{}"
    try:
        extra = json.loads(extra_raw)
    except json.JSONDecodeError:
        extra = {}
    return Order(
        id=row["id"],
        public_id=row["public_id"],
        client_tg_id=row["client_tg_id"],
        client_username=row["client_username"],
        amount_rub=row["amount_rub"],
        amount_usdt=row["amount_usdt"],
        rate=row["rate"],
        usdt_address=row["usdt_address"],
        status=OrderStatus(row["status"]),
        created_at=parse_dt(row["created_at"]) or utcnow(),
        updated_at=parse_dt(row["updated_at"]) or utcnow(),
        requisites_bank=row["requisites_bank"],
        requisites_detail=row["requisites_detail"],
        requisites_holder=row["requisites_holder"],
        requisites_sbp_url=row["requisites_sbp_url"],
        requisites_by=row["requisites_by"],
        requisites_at=parse_dt(row["requisites_at"]),
        payment_deadline_at=parse_dt(row["payment_deadline_at"]),
        receipt_file_id=row["receipt_file_id"],
        receipt_file_unique_id=row["receipt_file_unique_id"],
        receipt_check_status=row["receipt_check_status"],
        receipt_check_message=row["receipt_check_message"],
        receipt_check_raw=row["receipt_check_raw"],
        support_reviewed_by=row["support_reviewed_by"],
        support_reviewed_at=parse_dt(row["support_reviewed_at"]),
        support_note=row["support_note"],
        payout_txid=row["payout_txid"],
        payout_by=row["payout_by"],
        payout_at=parse_dt(row["payout_at"]),
        cancel_reason=row["cancel_reason"],
        extra=extra,
    )


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def create_order(
        self,
        *,
        client_tg_id: int,
        client_username: str | None,
        amount_rub: float,
        amount_usdt: float,
        rate: float,
        usdt_address: str,
        extra: dict | None = None,
    ) -> Order:
        now = iso(utcnow())
        public_id = _new_public_id()
        extra_json = json.dumps(extra or {}, ensure_ascii=False)
        for _ in range(5):
            try:
                cursor = await self.conn.execute(
                    """
                    INSERT INTO orders (
                        public_id, client_tg_id, client_username,
                        amount_rub, amount_usdt, rate, usdt_address,
                        status, extra_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        public_id,
                        client_tg_id,
                        client_username,
                        amount_rub,
                        amount_usdt,
                        rate,
                        usdt_address,
                        OrderStatus.AWAITING_REQUISITES.value,
                        extra_json,
                        now,
                        now,
                    ),
                )
                await self.conn.commit()
                return await self.get_order_by_id(cursor.lastrowid)  # type: ignore[arg-type]
            except aiosqlite.IntegrityError:
                public_id = _new_public_id()
        raise RuntimeError("Failed to allocate unique public_id")

    async def get_order_by_id(self, order_id: int) -> Order | None:
        cursor = await self.conn.execute(
            "SELECT * FROM orders WHERE id = ?", (order_id,)
        )
        row = await cursor.fetchone()
        return _row_to_order(row) if row else None

    async def get_order_by_public_id(self, public_id: str) -> Order | None:
        cursor = await self.conn.execute(
            "SELECT * FROM orders WHERE public_id = ?", (public_id.upper(),)
        )
        row = await cursor.fetchone()
        return _row_to_order(row) if row else None

    async def list_by_statuses(
        self, statuses: Iterable[OrderStatus], *, limit: int = 20
    ) -> list[Order]:
        status_values = [s.value for s in statuses]
        if not status_values:
            return []
        placeholders = ",".join("?" for _ in status_values)
        cursor = await self.conn.execute(
            f"""
            SELECT * FROM orders
            WHERE status IN ({placeholders})
            ORDER BY id ASC
            LIMIT ?
            """,
            (*status_values, limit),
        )
        rows = await cursor.fetchall()
        return [_row_to_order(r) for r in rows]

    async def list_client_orders(
        self, client_tg_id: int, *, limit: int = 10
    ) -> list[Order]:
        cursor = await self.conn.execute(
            """
            SELECT * FROM orders
            WHERE client_tg_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (client_tg_id, limit),
        )
        rows = await cursor.fetchall()
        return [_row_to_order(r) for r in rows]

    async def active_client_order(self, client_tg_id: int) -> Order | None:
        from exchange.statuses import CLIENT_VISIBLE_ACTIVE

        statuses = list(CLIENT_VISIBLE_ACTIVE)
        placeholders = ",".join("?" for _ in statuses)
        cursor = await self.conn.execute(
            f"""
            SELECT * FROM orders
            WHERE client_tg_id = ? AND status IN ({placeholders})
            ORDER BY id DESC
            LIMIT 1
            """,
            (client_tg_id, *[s.value for s in statuses]),
        )
        row = await cursor.fetchone()
        return _row_to_order(row) if row else None

    async def update_fields(self, order_id: int, **fields: object) -> Order:
        if not fields:
            order = await self.get_order_by_id(order_id)
            if order is None:
                raise KeyError(order_id)
            return order

        fields = dict(fields)
        fields["updated_at"] = iso(utcnow())
        if "status" in fields and isinstance(fields["status"], OrderStatus):
            fields["status"] = fields["status"].value
        if "extra" in fields:
            fields["extra_json"] = json.dumps(fields.pop("extra"), ensure_ascii=False)

        columns = ", ".join(f"{key} = ?" for key in fields)
        await self.conn.execute(
            f"UPDATE orders SET {columns} WHERE id = ?",
            (*fields.values(), order_id),
        )
        await self.conn.commit()
        order = await self.get_order_by_id(order_id)
        if order is None:
            raise KeyError(order_id)
        return order

    async def assign_requisites(
        self,
        order_id: int,
        *,
        support_tg_id: int,
        requisites: Requisites,
        ttl_minutes: int,
    ) -> Order:
        now = utcnow()
        deadline = now + timedelta(minutes=ttl_minutes)
        return await self.update_fields(
            order_id,
            status=OrderStatus.AWAITING_PAYMENT,
            requisites_bank=requisites.bank,
            requisites_detail=requisites.detail,
            requisites_holder=requisites.holder or None,
            requisites_sbp_url=requisites.sbp_url or None,
            requisites_by=support_tg_id,
            requisites_at=iso(now),
            payment_deadline_at=iso(deadline),
        )

    async def list_orders_since(self, since: datetime) -> list[Order]:
        """Заявки, созданные начиная с момента since (для статистики)."""
        cursor = await self.conn.execute(
            "SELECT * FROM orders WHERE created_at >= ? ORDER BY id ASC",
            (iso(since),),
        )
        rows = await cursor.fetchall()
        return [_row_to_order(r) for r in rows]

    # ----- Карточки в группе сотрудников -----

    async def get_staff_card(self, order_id: int) -> tuple[int, int, str] | None:
        """(chat_id, message_id, status) или None."""
        cursor = await self.conn.execute(
            "SELECT chat_id, message_id, status FROM staff_cards WHERE order_id = ?",
            (order_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return int(row["chat_id"]), int(row["message_id"]), str(row["status"])

    async def set_staff_card(
        self, order_id: int, *, chat_id: int, message_id: int, status: str
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO staff_cards (order_id, chat_id, message_id, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                chat_id = excluded.chat_id,
                message_id = excluded.message_id,
                status = excluded.status
            """,
            (order_id, chat_id, message_id, status),
        )
        await self.conn.commit()

    # ----- Кто ведёт заявку -----

    async def get_owner(self, order_id: int) -> tuple[int, str] | None:
        """(tg_id, имя) сотрудника, который ведёт заявку, или None."""
        cursor = await self.conn.execute(
            "SELECT tg_id, name FROM order_owners WHERE order_id = ?", (order_id,)
        )
        row = await cursor.fetchone()
        return (int(row["tg_id"]), str(row["name"])) if row else None

    async def take_order(self, order_id: int, *, tg_id: int, name: str) -> tuple[int, str]:
        """
        Закрепить заявку за сотрудником, если она свободна.
        Возвращает фактического владельца (если успел другой — его).
        """
        await self.conn.execute(
            """
            INSERT OR IGNORE INTO order_owners (order_id, tg_id, name, taken_at)
            VALUES (?, ?, ?, ?)
            """,
            (order_id, tg_id, name, iso(utcnow())),
        )
        await self.conn.commit()
        owner = await self.get_owner(order_id)
        assert owner is not None
        return owner

    async def release_order(self, order_id: int) -> None:
        await self.conn.execute("DELETE FROM order_owners WHERE order_id = ?", (order_id,))
        await self.conn.commit()

    async def owners_for(self, order_ids: Iterable[int]) -> dict[int, tuple[int, str]]:
        ids = list(order_ids)
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        cursor = await self.conn.execute(
            f"SELECT order_id, tg_id, name FROM order_owners WHERE order_id IN ({placeholders})",
            ids,
        )
        rows = await cursor.fetchall()
        return {int(r["order_id"]): (int(r["tg_id"]), str(r["name"])) for r in rows}

    async def expire_overdue(self, now: datetime | None = None) -> list[Order]:
        now = now or utcnow()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        cursor = await self.conn.execute(
            """
            SELECT * FROM orders
            WHERE status = ? AND payment_deadline_at IS NOT NULL
              AND payment_deadline_at < ?
            """,
            (OrderStatus.AWAITING_PAYMENT.value, iso(now)),
        )
        rows = await cursor.fetchall()
        expired: list[Order] = []
        for row in rows:
            order = await self.update_fields(
                row["id"],
                status=OrderStatus.EXPIRED,
                cancel_reason="Истёк срок оплаты по реквизитам",
            )
            expired.append(order)
        return expired
