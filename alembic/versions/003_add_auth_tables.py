"""add users, tenants, user_tenants tables

Revision ID: 003_add_auth_tables
Revises: 002_add_tenant_channels
Create Date: 2026-04-16
"""

import sqlalchemy as sa
from alembic import op

revision = "003_add_auth_tables"
down_revision = "002_add_tenant_channels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── tenants ───────────────────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
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
        sa.Column("name", sa.String(120), nullable=True),
    )

    # ── users ─────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
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
        sa.Column("email", sa.String(254), nullable=False),
        # bcrypt output is always 60 chars; 72 gives headroom
        sa.Column("password_hash", sa.String(72), nullable=True),
        sa.Column(
            "auth_provider", sa.String(20), nullable=False, server_default="email"
        ),
        sa.Column("display_name", sa.String(120), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_unique_constraint("uq_users_email", "users", ["email"])

    # ── user_tenants ──────────────────────────────────────────────────────────
    op.create_table(
        "user_tenants",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
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
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
    )
    op.create_index("ix_user_tenants_user_id", "user_tenants", ["user_id"])
    op.create_index("ix_user_tenants_tenant_id", "user_tenants", ["tenant_id"])
    op.create_unique_constraint(
        "uq_user_tenants_user_tenant", "user_tenants", ["user_id", "tenant_id"]
    )


def downgrade() -> None:
    op.drop_table("user_tenants")
    op.drop_table("users")
    op.drop_table("tenants")
