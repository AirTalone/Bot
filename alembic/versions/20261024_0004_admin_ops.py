"""admin ops tables

Revision ID: 20261024_0004
Revises: 20261024_0003
Create Date: 2026-10-24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261024_0004"
down_revision: Union[str, Sequence[str], None] = "20261024_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runtime_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("maintenance", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("admin_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_admin_audit_logs_admin_telegram_id"), "admin_audit_logs", ["admin_telegram_id"])
    op.create_index(op.f("ix_admin_audit_logs_action"), "admin_audit_logs", ["action"])
    op.create_index(op.f("ix_admin_audit_logs_order_id"), "admin_audit_logs", ["order_id"])
    op.create_index(op.f("ix_admin_audit_logs_created_at"), "admin_audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_audit_logs_created_at"), table_name="admin_audit_logs")
    op.drop_index(op.f("ix_admin_audit_logs_order_id"), table_name="admin_audit_logs")
    op.drop_index(op.f("ix_admin_audit_logs_action"), table_name="admin_audit_logs")
    op.drop_index(op.f("ix_admin_audit_logs_admin_telegram_id"), table_name="admin_audit_logs")
    op.drop_table("admin_audit_logs")
    op.drop_table("runtime_state")
