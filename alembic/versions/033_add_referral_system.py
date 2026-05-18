"""Add referral system — referral_code on traders, marketing_agents, referrals tables

Revision ID: 033_add_referral_system
Revises: 032_add_interest_events
"""
from alembic import op
import sqlalchemy as sa

revision = "033_add_referral_system"
down_revision = "032_add_interest_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add referral fields to traders
    op.add_column("traders", sa.Column("referral_code", sa.String(60), nullable=True, unique=True))
    op.add_column("traders", sa.Column("attribution_type", sa.String(20), nullable=True))
    op.add_column("traders", sa.Column("attribution_code", sa.String(60), nullable=True))

    # Marketing agents table
    op.create_table(
        "marketing_agents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_code", sa.String(30), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("phone_number", sa.String(20), nullable=False, unique=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("total_earned", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_paid", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_payout_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # Referrals tracking table
    op.create_table(
        "referrals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("referrer_phone", sa.String(40), nullable=True),
        sa.Column("agent_code", sa.String(30), nullable=True),
        sa.Column("referred_phone", sa.String(40), nullable=False),
        sa.Column("referred_name", sa.String(200), nullable=True),
        sa.Column("attribution_type", sa.String(20), nullable=False, server_default="organic"),
        sa.Column("status", sa.String(20), nullable=False, server_default="signed_up"),
        sa.Column("first_order_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active_30d_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reward_given", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("reward_amount", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_referrals_referrer", "referrals", ["referrer_phone"])
    op.create_index("ix_referrals_referred", "referrals", ["referred_phone"])
    op.create_index("ix_referrals_agent", "referrals", ["agent_code"])


def downgrade() -> None:
    op.drop_index("ix_referrals_agent")
    op.drop_index("ix_referrals_referred")
    op.drop_index("ix_referrals_referrer")
    op.drop_table("referrals")
    op.drop_table("marketing_agents")
    op.drop_column("traders", "attribution_code")
    op.drop_column("traders", "attribution_type")
    op.drop_column("traders", "referral_code")
