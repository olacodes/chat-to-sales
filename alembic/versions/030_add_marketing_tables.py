"""030: Add marketing tables — customer_list, broadcasts, broadcast_recipients.

Revision ID: 030_add_marketing_tables
"""

from alembic import op
import sqlalchemy as sa

revision = "030_add_marketing_tables"
down_revision = "029_add_product_image_nobg_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Customer list
    op.create_table(
        "customer_list",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("trader_phone", sa.String(40), nullable=False),
        sa.Column("customer_phone", sa.String(40), nullable=False),
        sa.Column("customer_name", sa.String(200), nullable=True),
        sa.Column("total_orders", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_spend", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("first_order_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_order_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opted_out", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("opted_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_broadcast_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("trader_phone", "customer_phone", name="uq_customer_list_trader_customer"),
    )
    op.create_index("ix_customer_list_trader", "customer_list", ["trader_phone"])

    # Broadcasts
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("trader_phone", sa.String(40), nullable=False),
        sa.Column("segment", sa.String(100), nullable=False),
        sa.Column("message_text", sa.Text, nullable=False),
        sa.Column("original_text", sa.Text, nullable=True),
        sa.Column("total_recipients", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("delivered_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("read_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reply_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("order_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("order_revenue", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_broadcasts_trader", "broadcasts", ["trader_phone"])

    # Broadcast recipients
    op.create_table(
        "broadcast_recipients",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("broadcast_id", sa.String(36), sa.ForeignKey("broadcasts.id"), nullable=False),
        sa.Column("customer_phone", sa.String(40), nullable=False),
        sa.Column("customer_name", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("order_id", sa.String(36), nullable=True),
        sa.Column("skip_reason", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_broadcast_recipients_broadcast", "broadcast_recipients", ["broadcast_id"])
    op.create_index("ix_broadcast_recipients_customer", "broadcast_recipients", ["customer_phone"])


def downgrade() -> None:
    op.drop_table("broadcast_recipients")
    op.drop_table("broadcasts")
    op.drop_table("customer_list")
