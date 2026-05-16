"""Add segments JSON column to customer_list

Revision ID: 031
Revises: 030
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "031_add_customer_segments"
down_revision = "030_add_marketing_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customer_list", sa.Column("segments", JSONB, nullable=True))
    op.add_column("customer_list", sa.Column("segments_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("customer_list", "segments_updated_at")
    op.drop_column("customer_list", "segments")
