"""order panel fields

Revision ID: 20261024_0002
Revises: 20261024_0001
Create Date: 2026-10-24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261024_0002"
down_revision: Union[str, Sequence[str], None] = "20261024_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("panel_username", sa.String(length=64), nullable=True))
    op.add_column("orders", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_orders_panel_username"), "orders", ["panel_username"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_orders_panel_username"), table_name="orders")
    op.drop_column("orders", "expires_at")
    op.drop_column("orders", "panel_username")
