"""add tenant_report_configs and weekly_reports tables

Revision ID: 005_add_report_tables
Revises: 004_add_conversation_assignment
Create Date: 2026-04-22
"""

import sqlalchemy as sa
from alembic import op

revision = "005_add_report_tables"
down_revision = "004_add_conversation_assignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── tenant_report_configs ──────────────────────────────────────────────────
    op.create_table(
        "tenant_report_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("recipient_phone", sa.String(40), nullable=True),
        sa.Column("timezone", sa.String(60), nullable=False, server_default="Africa/Lagos"),
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
        sa.UniqueConstraint("tenant_id", name="uq_report_config_tenant"),
    )
    op.create_index(
        "ix_tenant_report_configs_tenant_id",
        "tenant_report_configs",
        ["tenant_id"],
    )

    # ── weekly_reports ─────────────────────────────────────────────────────────
    op.create_table(
        "weekly_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("week_start", sa.String(10), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("recipient_phone", sa.String(40), nullable=True),
        sa.Column("report_text", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
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
    op.create_index("ix_weekly_reports_tenant_id", "weekly_reports", ["tenant_id"])
    op.create_index(
        "ix_weekly_reports_tenant_week",
        "weekly_reports",
        ["tenant_id", "week_start"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_weekly_reports_tenant_week", table_name="weekly_reports")
    op.drop_index("ix_weekly_reports_tenant_id", table_name="weekly_reports")
    op.drop_table("weekly_reports")
    op.drop_index("ix_tenant_report_configs_tenant_id", table_name="tenant_report_configs")
    op.drop_table("tenant_report_configs")
