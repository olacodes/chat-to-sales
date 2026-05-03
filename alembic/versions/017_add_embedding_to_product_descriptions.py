"""add embedding column to product_descriptions

Revision ID: 017_add_embedding_to_product_descriptions
Revises: 016_add_product_descriptions
Create Date: 2026-05-03
"""

import sqlalchemy as sa
from alembic import op

revision = "017_add_embedding_to_product_descriptions"
down_revision = "016_add_product_descriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_descriptions",
        sa.Column("embedding", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("product_descriptions", "embedding")
