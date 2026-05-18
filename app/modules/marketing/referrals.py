"""
app/modules/marketing/referrals.py

Referral & marketing agent tracking system.

Models:
  MarketingAgent — field marketers who sign up traders
  Referral — tracks each referral/attribution through milestones

Functions:
  generate_referral_code — creates REF-{slug} from business name
  log_referral — records a new referral
  advance_referral — moves referral to next milestone
"""

import re
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    Boolean, DateTime, Index, Integer,
    Numeric, String, Text, UniqueConstraint,
    select, update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.logging import get_logger
from app.core.models.base import BaseModel

logger = get_logger(__name__)


# ── Enums ────────────────────────────────────────────────────────────────────


class AttributionType(StrEnum):
    ORGANIC = "organic"
    REFERRAL = "referral"
    AGENT = "agent"
    PARTNERSHIP = "partnership"


class ReferralStatus(StrEnum):
    SIGNED_UP = "signed_up"
    FIRST_ORDER = "first_order"
    ACTIVE_30D = "active_30d"
    CONVERTED = "converted"


# ── Marketing Agent Model ────────────────────────────────────────────────────


class MarketingAgent(BaseModel):
    __tablename__ = "marketing_agents"
    __table_args__ = (
        UniqueConstraint("agent_code", name="uq_marketing_agents_code"),
        UniqueConstraint("phone_number", name="uq_marketing_agents_phone"),
    )

    agent_code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    total_earned: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_paid: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_payout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Referral Model ───────────────────────────────────────────────────────────


class Referral(BaseModel):
    __tablename__ = "referrals"
    __table_args__ = (
        Index("ix_referrals_referrer", "referrer_phone"),
        Index("ix_referrals_referred", "referred_phone"),
        Index("ix_referrals_agent", "agent_code"),
    )

    # Who referred
    referrer_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)  # trader referral
    agent_code: Mapped[str | None] = mapped_column(String(30), nullable=True)  # agent attribution

    # Who was referred
    referred_phone: Mapped[str] = mapped_column(String(40), nullable=False)
    referred_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    attribution_type: Mapped[str] = mapped_column(String(20), nullable=False, default=AttributionType.ORGANIC)

    # Milestone tracking
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ReferralStatus.SIGNED_UP)
    first_order_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active_30d_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Reward tracking
    reward_given: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    reward_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


# ── Helper functions ─────────────────────────────────────────────────────────


def generate_referral_code(business_name: str) -> str:
    """Generate REF-{slug} from business name. E.g. 'Mama Caro Provisions' → 'REF-MAMA-CARO'."""
    slug = re.sub(r"[^a-zA-Z0-9\s]", "", business_name).strip()
    parts = slug.upper().split()[:3]  # max 3 words
    if not parts:
        import uuid
        return f"REF-{uuid.uuid4().hex[:6].upper()}"
    return f"REF-{'-'.join(parts)}"


def generate_agent_code(name: str) -> str:
    """Generate AGT-{slug}-{random} for an agent."""
    import uuid
    slug = re.sub(r"[^a-zA-Z0-9]", "", name).strip().upper()[:8]
    short = uuid.uuid4().hex[:4].upper()
    return f"AGT-{slug}-{short}" if slug else f"AGT-{short}"


async def ensure_unique_referral_code(db: AsyncSession, base_code: str) -> str:
    """Append -2, -3, etc. if the code is already taken."""
    from app.modules.onboarding.models import Trader
    code = base_code
    suffix = 2
    while True:
        result = await db.execute(
            select(Trader.id).where(Trader.referral_code == code)
        )
        if result.scalar_one_or_none() is None:
            return code
        code = f"{base_code}-{suffix}"
        suffix += 1


async def log_referral(
    db: AsyncSession,
    *,
    referred_phone: str,
    referred_name: str | None = None,
    referrer_phone: str | None = None,
    agent_code: str | None = None,
    attribution_type: str = AttributionType.ORGANIC,
) -> Referral:
    """Record a new referral when a trader completes onboarding."""
    # Check for duplicate
    existing = (await db.execute(
        select(Referral).where(Referral.referred_phone == referred_phone)
    )).scalar_one_or_none()
    if existing:
        return existing

    referral = Referral(
        referrer_phone=referrer_phone,
        agent_code=agent_code,
        referred_phone=referred_phone,
        referred_name=referred_name,
        attribution_type=attribution_type,
        status=ReferralStatus.SIGNED_UP,
    )
    db.add(referral)
    await db.flush()
    logger.info(
        "Referral logged: referred=%s type=%s referrer=%s agent=%s",
        referred_phone, attribution_type, referrer_phone, agent_code,
    )
    return referral


async def advance_referral_to_first_order(db: AsyncSession, trader_phone: str) -> None:
    """Called when a referred trader receives their first paid order."""
    now = datetime.now(tz=timezone.utc)
    await db.execute(
        update(Referral)
        .where(
            Referral.referred_phone == trader_phone,
            Referral.status == ReferralStatus.SIGNED_UP,
        )
        .values(status=ReferralStatus.FIRST_ORDER, first_order_at=now)
    )


async def advance_referral_to_active(db: AsyncSession, trader_phone: str) -> None:
    """Called when a referred trader has been active for 30 days with 3+ orders."""
    now = datetime.now(tz=timezone.utc)
    await db.execute(
        update(Referral)
        .where(
            Referral.referred_phone == trader_phone,
            Referral.status == ReferralStatus.FIRST_ORDER,
        )
        .values(status=ReferralStatus.ACTIVE_30D, active_30d_at=now)
    )


async def advance_referral_to_converted(db: AsyncSession, trader_phone: str) -> None:
    """Called when a referred trader converts to a paid subscription."""
    now = datetime.now(tz=timezone.utc)
    await db.execute(
        update(Referral)
        .where(
            Referral.referred_phone == trader_phone,
            Referral.status.in_([ReferralStatus.SIGNED_UP, ReferralStatus.FIRST_ORDER, ReferralStatus.ACTIVE_30D]),
        )
        .values(status=ReferralStatus.CONVERTED, converted_at=now)
    )


async def get_referral_stats(db: AsyncSession, referrer_phone: str) -> dict:
    """Get referral stats for a trader's REFER command."""
    from sqlalchemy import func
    result = await db.execute(
        select(
            func.count(Referral.id).label("total"),
            func.count(Referral.id).filter(Referral.status != ReferralStatus.SIGNED_UP).label("active"),
            func.count(Referral.id).filter(Referral.status == ReferralStatus.CONVERTED).label("converted"),
        ).where(Referral.referrer_phone == referrer_phone)
    )
    row = result.one()
    return {
        "total": row.total,
        "active": row.active,
        "converted": row.converted,
    }
