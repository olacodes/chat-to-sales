"""add reminder_sent_at to orders

Revision ID: 022_add_order_reminder_sent_at
Revises: 021_add_onboarding_events
Create Date: 2026-05-06
"""

import sqlalchemy as sa
from alembic import op

revision = "022_add_order_reminder_sent_at"
down_revision = "021_add_onboarding_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "reminder_sent_at")
