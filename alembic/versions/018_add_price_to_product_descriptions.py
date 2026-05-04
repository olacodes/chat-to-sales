"""add price column to product_descriptions

Revision ID: 018_add_price_to_product_descriptions
Revises: 017_add_embedding_to_product_descriptions
Create Date: 2026-05-03
"""

import sqlalchemy as sa
from alembic import op

revision = "018_add_price_to_product_descriptions"
down_revision = "017_add_embedding_to_product_descriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_descriptions",
        sa.Column("price", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("product_descriptions", "price")
