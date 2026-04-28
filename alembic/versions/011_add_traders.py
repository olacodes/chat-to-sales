"""add traders table

Revision ID: 011_add_traders
Revises: 010_add_credit_sales
Create Date: 2026-04-27
"""

import sqlalchemy as sa
from alembic import op

revision = "011_add_traders"
down_revision = "010_add_credit_sales"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "traders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("business_name", sa.String(120), nullable=True),
        sa.Column("business_category", sa.String(60), nullable=True),
        sa.Column("store_slug", sa.String(120), nullable=True),
        sa.Column(
            "onboarding_status",
            sa.String(20),
            nullable=False,
            server_default="in_progress",
        ),
        sa.Column(
            "tier",
            sa.String(20),
            nullable=False,
            server_default="ofe",
        ),
        sa.Column("onboarding_catalogue", sa.Text, nullable=True),
    )

    op.create_unique_constraint(
        "uq_traders_phone_number", "traders", ["phone_number"]
    )
    op.create_unique_constraint(
        "uq_traders_store_slug", "traders", ["store_slug"]
    )
    op.create_index("ix_traders_phone_number", "traders", ["phone_number"])
    op.create_index("ix_traders_store_slug", "traders", ["store_slug"])


def downgrade() -> None:
    op.drop_index("ix_traders_store_slug", table_name="traders")
    op.drop_index("ix_traders_phone_number", table_name="traders")
    op.drop_constraint("uq_traders_store_slug", "traders", type_="unique")
    op.drop_constraint("uq_traders_phone_number", "traders", type_="unique")
    op.drop_table("traders")
