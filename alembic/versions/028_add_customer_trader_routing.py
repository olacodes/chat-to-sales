"""028: Add customer_trader_routing table for persistent routing.

Revision ID: 028
"""

from alembic import op
import sqlalchemy as sa

revision = "028_add_customer_trader_routing"
down_revision = "027_add_product_images"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_trader_routing",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_phone", sa.String(40), nullable=False),
        sa.Column("trader_phone", sa.String(40), nullable=False),
        sa.Column("store_slug", sa.String(200), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_customer_trader_routing_customer",
        "customer_trader_routing",
        ["customer_phone"],
        unique=False,
    )
    # Unique on customer_phone — one active routing per customer
    op.create_index(
        "uq_customer_trader_routing_phone",
        "customer_trader_routing",
        ["customer_phone"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("customer_trader_routing")
