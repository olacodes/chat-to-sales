"""
Service tests for smart follow-up — interest logging, dedup, pending lookup.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketing.followup import (
    InterestEvent,
    InterestType,
    log_interest,
    get_pending_followups,
    mark_followed_up,
    mark_converted,
)


class TestLogInterest:
    @pytest.mark.asyncio
    async def test_creates_event(self, db_session: AsyncSession):
        event = await log_interest(
            db_session,
            tenant_id="t1",
            trader_phone="234trader",
            customer_phone="234customer",
            customer_name="Bimpe",
            product_name="iPhone 12",
            price=330000,
            event_type=InterestType.PRICE_INQUIRY,
        )
        assert event.id is not None
        assert event.trader_phone == "234trader"
        assert event.product_name == "iPhone 12"
        assert event.price == 330000
        assert event.followed_up is False
        assert event.converted is False

    @pytest.mark.asyncio
    async def test_deduplicates_within_48h(self, db_session: AsyncSession):
        e1 = await log_interest(
            db_session,
            tenant_id="t1", trader_phone="234t", customer_phone="234c",
            customer_name=None, product_name="Garri", price=2500,
            event_type=InterestType.ORDER_CANCELLED,
        )
        e2 = await log_interest(
            db_session,
            tenant_id="t1", trader_phone="234t", customer_phone="234c",
            customer_name=None, product_name="Garri", price=2500,
            event_type=InterestType.ORDER_CANCELLED,
        )
        assert e1.id == e2.id  # same event returned

    @pytest.mark.asyncio
    async def test_different_products_not_deduped(self, db_session: AsyncSession):
        e1 = await log_interest(
            db_session,
            tenant_id="t1", trader_phone="234t", customer_phone="234c",
            customer_name=None, product_name="Garri", price=2500,
            event_type=InterestType.PRICE_INQUIRY,
        )
        e2 = await log_interest(
            db_session,
            tenant_id="t1", trader_phone="234t", customer_phone="234c",
            customer_name=None, product_name="Rice", price=63000,
            event_type=InterestType.PRICE_INQUIRY,
        )
        assert e1.id != e2.id

    @pytest.mark.asyncio
    async def test_different_customers_not_deduped(self, db_session: AsyncSession):
        e1 = await log_interest(
            db_session,
            tenant_id="t1", trader_phone="234t", customer_phone="234c1",
            customer_name=None, product_name="Garri", price=2500,
            event_type=InterestType.PRICE_INQUIRY,
        )
        e2 = await log_interest(
            db_session,
            tenant_id="t1", trader_phone="234t", customer_phone="234c2",
            customer_name=None, product_name="Garri", price=2500,
            event_type=InterestType.PRICE_INQUIRY,
        )
        assert e1.id != e2.id


class TestGetPendingFollowups:
    @pytest.mark.asyncio
    async def test_returns_old_events(self, db_session: AsyncSession):
        event = InterestEvent(
            tenant_id="t1", trader_phone="234t", customer_phone="234c",
            product_name="iPhone", price=330000,
            event_type=InterestType.PRICE_INQUIRY,
        )
        db_session.add(event)
        await db_session.flush()

        # Manually backdate the created_at
        event.created_at = datetime.now(tz=timezone.utc) - timedelta(hours=25)
        await db_session.flush()

        pending = await get_pending_followups(db_session, min_age_hours=24)
        assert len(pending) == 1
        assert pending[0].id == event.id

    @pytest.mark.asyncio
    async def test_excludes_recent_events(self, db_session: AsyncSession):
        event = InterestEvent(
            tenant_id="t1", trader_phone="234t", customer_phone="234c",
            product_name="iPhone", price=330000,
            event_type=InterestType.PRICE_INQUIRY,
        )
        db_session.add(event)
        await db_session.flush()

        # Event just created (< 24h old)
        pending = await get_pending_followups(db_session, min_age_hours=24)
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_excludes_already_followed_up(self, db_session: AsyncSession):
        event = InterestEvent(
            tenant_id="t1", trader_phone="234t", customer_phone="234c",
            product_name="iPhone", price=330000,
            event_type=InterestType.PRICE_INQUIRY,
            followed_up=True,
        )
        db_session.add(event)
        await db_session.flush()
        event.created_at = datetime.now(tz=timezone.utc) - timedelta(hours=25)
        await db_session.flush()

        pending = await get_pending_followups(db_session, min_age_hours=24)
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_excludes_converted(self, db_session: AsyncSession):
        event = InterestEvent(
            tenant_id="t1", trader_phone="234t", customer_phone="234c",
            product_name="iPhone", price=330000,
            event_type=InterestType.PRICE_INQUIRY,
            converted=True, order_id="order-123",
        )
        db_session.add(event)
        await db_session.flush()
        event.created_at = datetime.now(tz=timezone.utc) - timedelta(hours=25)
        await db_session.flush()

        pending = await get_pending_followups(db_session, min_age_hours=24)
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_respects_limit(self, db_session: AsyncSession):
        for i in range(5):
            event = InterestEvent(
                tenant_id="t1", trader_phone="234t", customer_phone=f"234c{i}",
                product_name="Garri", price=2500,
                event_type=InterestType.PRICE_INQUIRY,
            )
            db_session.add(event)
        await db_session.flush()

        # Backdate all
        result = await db_session.execute(select(InterestEvent))
        for e in result.scalars().all():
            e.created_at = datetime.now(tz=timezone.utc) - timedelta(hours=25)
        await db_session.flush()

        pending = await get_pending_followups(db_session, min_age_hours=24, limit=3)
        assert len(pending) == 3


class TestMarkFollowedUp:
    @pytest.mark.asyncio
    async def test_marks_followed_up(self, db_session: AsyncSession):
        event = InterestEvent(
            tenant_id="t1", trader_phone="234t", customer_phone="234c",
            product_name="Garri", price=2500,
            event_type=InterestType.ORDER_CANCELLED,
        )
        db_session.add(event)
        await db_session.flush()

        await mark_followed_up(db_session, event.id)
        await db_session.flush()

        refreshed = (await db_session.execute(
            select(InterestEvent).where(InterestEvent.id == event.id)
        )).scalar_one()
        assert refreshed.followed_up is True
        assert refreshed.followed_up_at is not None


class TestMarkConverted:
    @pytest.mark.asyncio
    async def test_marks_converted(self, db_session: AsyncSession):
        event = InterestEvent(
            tenant_id="t1", trader_phone="234t", customer_phone="234c",
            product_name="Garri", price=2500,
            event_type=InterestType.PRICE_INQUIRY,
        )
        db_session.add(event)
        await db_session.flush()

        await mark_converted(
            db_session,
            trader_phone="234t", customer_phone="234c",
            product_name="Garri", order_id="order-456",
        )
        await db_session.flush()

        refreshed = (await db_session.execute(
            select(InterestEvent).where(InterestEvent.id == event.id)
        )).scalar_one()
        assert refreshed.converted is True
        assert refreshed.order_id == "order-456"

    @pytest.mark.asyncio
    async def test_does_not_mark_already_converted(self, db_session: AsyncSession):
        event = InterestEvent(
            tenant_id="t1", trader_phone="234t", customer_phone="234c",
            product_name="Garri", price=2500,
            event_type=InterestType.PRICE_INQUIRY,
            converted=True, order_id="order-111",
        )
        db_session.add(event)
        await db_session.flush()

        await mark_converted(
            db_session,
            trader_phone="234t", customer_phone="234c",
            product_name="Garri", order_id="order-222",
        )
        await db_session.flush()

        refreshed = (await db_session.execute(
            select(InterestEvent).where(InterestEvent.id == event.id)
        )).scalar_one()
        assert refreshed.order_id == "order-111"  # unchanged
