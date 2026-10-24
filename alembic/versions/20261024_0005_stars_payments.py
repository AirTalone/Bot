"""stars payments fields

Revision ID: 20261024_0005
Revises: 20261024_0004
Create Date: 2026-10-24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261024_0005"
down_revision: Union[str, Sequence[str], None] = "20261024_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tariffs",
        sa.Column("stars_price", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "orders",
        sa.Column("payment_method", sa.String(length=16), nullable=False, server_default="qr"),
    )
    op.add_column("orders", sa.Column("stars_amount", sa.Integer(), nullable=True))
    op.add_column(
        "orders",
        sa.Column("telegram_payment_charge_id", sa.String(length=128), nullable=True),
    )
    op.create_index(
        op.f("ix_orders_telegram_payment_charge_id"),
        "orders",
        ["telegram_payment_charge_id"],
        unique=True,
    )
    # Seed defaults for known tariffs (idempotent UPDATE by slug).
    op.execute("UPDATE tariffs SET stars_price = 75 WHERE slug = 'month_1' AND stars_price = 0")
    op.execute("UPDATE tariffs SET stars_price = 180 WHERE slug = 'month_3' AND stars_price = 0")
    op.execute("UPDATE tariffs SET stars_price = 300 WHERE slug = 'month_6' AND stars_price = 0")


def downgrade() -> None:
    op.drop_index(op.f("ix_orders_telegram_payment_charge_id"), table_name="orders")
    op.drop_column("orders", "telegram_payment_charge_id")
    op.drop_column("orders", "stars_amount")
    op.drop_column("orders", "payment_method")
    op.drop_column("tariffs", "stars_price")
