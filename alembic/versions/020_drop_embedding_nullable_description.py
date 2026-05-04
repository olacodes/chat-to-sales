"""drop embedding column, make description nullable

Revision ID: 020_drop_embedding_nullable_description
Revises: 019_add_image_hash_to_product_descriptions
Create Date: 2026-05-04
"""

import sqlalchemy as sa
from alembic import op

revision = "020_drop_embedding_nullable_description"
down_revision = "019_add_image_hash_to_product_descriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("product_descriptions", "embedding")
    op.alter_column(
        "product_descriptions",
        "description",
        existing_type=sa.Text(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "product_descriptions",
        "description",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.add_column(
        "product_descriptions",
        sa.Column("embedding", sa.Text(), nullable=True),
    )
