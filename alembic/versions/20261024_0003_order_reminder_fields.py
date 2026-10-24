"""order reminder fields

Revision ID: 20261024_0003
Revises: 20261024_0002
Create Date: 2026-10-24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261024_0003"
down_revision: Union[str, Sequence[str], None] = "20261024_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("expired_notified_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "expired_notified_at")
    op.drop_column("orders", "reminder_sent_at")
