"""add onboarding_events table for funnel analytics

Revision ID: 021_add_onboarding_events
Revises: 020_drop_embedding_nullable_description
Create Date: 2026-05-05
"""

import sqlalchemy as sa
from alembic import op

revision = "021_add_onboarding_events"
down_revision = "020_drop_embedding_nullable_description"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "onboarding_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("step_name", sa.String(60), nullable=True),
        sa.Column("path", sa.String(20), nullable=True),
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
    op.create_index("ix_onboarding_events_phone", "onboarding_events", ["phone_number"])
    op.create_index("ix_onboarding_events_type", "onboarding_events", ["event_type"])
    op.create_index("ix_onboarding_events_created", "onboarding_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_onboarding_events_created", table_name="onboarding_events")
    op.drop_index("ix_onboarding_events_type", table_name="onboarding_events")
    op.drop_index("ix_onboarding_events_phone", table_name="onboarding_events")
    op.drop_table("onboarding_events")
