"""widen notifications.event_id from VARCHAR(36) to VARCHAR(100)

Compound keys such as "reply.<uuid>" (42 chars) exceed the original 36-char
limit, causing StringDataRightTruncationError on INSERT.

Revision ID: 006_widen_notification_event_id
Revises: 005_add_report_tables
Create Date: 2026-04-22
"""

import sqlalchemy as sa
from alembic import op

revision = "006_widen_notification_event_id"
down_revision = "005_add_report_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "notifications",
        "event_id",
        existing_type=sa.String(36),
        type_=sa.String(100),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "notifications",
        "event_id",
        existing_type=sa.String(100),
        type_=sa.String(36),
        existing_nullable=False,
    )
