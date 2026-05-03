"""add product_descriptions table

Revision ID: 016_add_product_descriptions
Revises: 015_add_user_is_superadmin
Create Date: 2026-05-03
"""

import sqlalchemy as sa
from alembic import op

revision = "016_add_product_descriptions"
down_revision = "015_add_user_is_superadmin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_descriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trader_phone", sa.String(20), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "confirmed",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
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
    )
    op.create_index(
        "ix_product_desc_trader_phone",
        "product_descriptions",
        ["trader_phone"],
    )
    op.create_index(
        "ix_product_desc_trader_product",
        "product_descriptions",
        ["trader_phone", "product_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_desc_trader_product", table_name="product_descriptions")
    op.drop_index("ix_product_desc_trader_phone", table_name="product_descriptions")
    op.drop_table("product_descriptions")
