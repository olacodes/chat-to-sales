"""Add interest_events table for smart follow-up

Revision ID: 032_add_interest_events
Revises: 031_add_customer_segments
"""
from alembic import op
import sqlalchemy as sa

revision = "032_add_interest_events"
down_revision = "031_add_customer_segments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interest_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("trader_phone", sa.String(40), nullable=False),
        sa.Column("customer_phone", sa.String(40), nullable=False),
        sa.Column("customer_name", sa.String(200), nullable=True),
        sa.Column("product_name", sa.String(300), nullable=False),
        sa.Column("price", sa.Integer, nullable=True),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("followed_up", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("followed_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("converted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("order_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_interest_events_trader", "interest_events", ["trader_phone"])
    op.create_index("ix_interest_events_pending", "interest_events", ["followed_up", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_interest_events_pending")
    op.drop_index("ix_interest_events_trader")
    op.drop_table("interest_events")
