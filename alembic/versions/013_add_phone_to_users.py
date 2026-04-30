"""add phone_number to users

Revision ID: 013_add_phone_to_users
Revises: 012_add_order_customer_phone_and_trader_tenant
Create Date: 2026-04-30
"""

import sqlalchemy as sa
from alembic import op

revision = "013_add_phone_to_users"
down_revision = "012_add_order_customer_phone_and_trader_tenant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("phone_number", sa.String(20), nullable=True),
    )
    # PostgreSQL allows multiple NULLs in a unique index — email/Google users
    # will all have NULL here and that is intentional.
    op.create_index(
        "ix_users_phone_number",
        "users",
        ["phone_number"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_phone_number", table_name="users")
    op.drop_column("users", "phone_number")
