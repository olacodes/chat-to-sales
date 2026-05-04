"""add image_hash column to product_descriptions

Revision ID: 019_add_image_hash_to_product_descriptions
Revises: 018_add_price_to_product_descriptions
Create Date: 2026-05-04
"""

import sqlalchemy as sa
from alembic import op

revision = "019_add_image_hash_to_product_descriptions"
down_revision = "018_add_price_to_product_descriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_descriptions",
        sa.Column("image_hash", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("product_descriptions", "image_hash")
