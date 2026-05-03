"""add is_superadmin to users

Revision ID: 015_add_user_is_superadmin
Revises: 014_add_order_trader_phone
Create Date: 2026-05-03
"""

import sqlalchemy as sa
from alembic import op

revision = "015_add_user_is_superadmin"
down_revision = "014_add_order_trader_phone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_superadmin",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_superadmin")
