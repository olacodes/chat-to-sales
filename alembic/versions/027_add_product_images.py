"""add product_images table

Revision ID: 027_add_product_images
Revises: 026_add_trader_bank_details
Create Date: 2026-05-12
"""

import sqlalchemy as sa
from alembic import op

revision = "027_add_product_images"
down_revision = "026_add_trader_bank_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_images",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trader_phone", sa.String(20), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("image_url", sa.String(500), nullable=False),
        sa.Column("image_hash", sa.String(64), nullable=True),
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
            nullable=False,
        ),
    )
    op.create_index("ix_product_images_trader", "product_images", ["trader_phone"])
    op.create_index(
        "ix_product_images_trader_product",
        "product_images",
        ["trader_phone", "product_name"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_product_images_trader_product", table_name="product_images")
    op.drop_index("ix_product_images_trader", table_name="product_images")
    op.drop_table("product_images")
