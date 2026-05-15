"""029: Add image_nobg_url to product_images for transparent background version.

Revision ID: 029_add_product_image_nobg_url
"""

from alembic import op
import sqlalchemy as sa

revision = "029_add_product_image_nobg_url"
down_revision = "028_add_customer_trader_routing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("product_images", sa.Column("image_nobg_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("product_images", "image_nobg_url")
