"""
Service tests for broadcast anti-spam checks.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketing.models import (
    Broadcast, BroadcastRecipient, BroadcastStatus,
    CustomerListEntry, RecipientStatus,
)
from app.modules.marketing.broadcast import (
    get_7day_skip_count,
    get_last_broadcast_to_segment,
)


@pytest_asyncio.fixture
async def trader_with_customers(db_session: AsyncSession):
    """Create a trader with 3 customers, one recently messaged."""
    now = datetime.now(tz=timezone.utc)
    c1 = CustomerListEntry(
        tenant_id="t1", trader_phone="234t", customer_phone="234c1",
        customer_name="Bimpe", total_orders=3, total_spend=Decimal("15000"),
        last_broadcast_at=now - timedelta(days=3),  # 3 days ago — within cap
    )
    c2 = CustomerListEntry(
        tenant_id="t1", trader_phone="234t", customer_phone="234c2",
        customer_name="Ade", total_orders=1, total_spend=Decimal("5000"),
        last_broadcast_at=now - timedelta(days=10),  # 10 days ago — outside cap
    )
    c3 = CustomerListEntry(
        tenant_id="t1", trader_phone="234t", customer_phone="234c3",
        customer_name="Mama Tayo", total_orders=5, total_spend=Decimal("250000"),
        last_broadcast_at=None,  # never messaged
    )
    db_session.add_all([c1, c2, c3])
    await db_session.flush()
    return [c1, c2, c3]


class TestGet7DaySkipCount:
    @pytest.mark.asyncio
    async def test_counts_recently_messaged(self, db_session: AsyncSession, trader_with_customers):
        # Patch async_session_factory to use our test session
        from unittest.mock import patch, AsyncMock
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _mock_session():
            yield db_session

        with patch("app.modules.marketing.broadcast.async_session_factory", side_effect=_mock_session):
            count = await get_7day_skip_count(
                "234t", ["234c1", "234c2", "234c3"],
            )
        # c1 was messaged 3 days ago (within 7-day window)
        # c2 was messaged 10 days ago (outside)
        # c3 was never messaged
        assert count == 1

    @pytest.mark.asyncio
    async def test_empty_list(self, db_session: AsyncSession):
        count = await get_7day_skip_count("234t", [])
        assert count == 0


class TestGetLastBroadcastToSegment:
    @pytest.mark.asyncio
    async def test_no_broadcasts(self, db_session: AsyncSession):
        from unittest.mock import patch
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _mock_session():
            yield db_session

        with patch("app.modules.marketing.broadcast.async_session_factory", side_effect=_mock_session):
            result = await get_last_broadcast_to_segment("234t", "all_customers")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_most_recent(self, db_session: AsyncSession):
        now = datetime.now(tz=timezone.utc)
        b1 = Broadcast(
            tenant_id="t1", trader_phone="234t", segment="all_customers",
            message_text="Hello", total_recipients=10, sent_count=10,
            status=BroadcastStatus.SENT,
            completed_at=now - timedelta(hours=10),
        )
        b2 = Broadcast(
            tenant_id="t1", trader_phone="234t", segment="all_customers",
            message_text="Hi again", total_recipients=10, sent_count=10,
            status=BroadcastStatus.SENT,
            completed_at=now - timedelta(hours=2),
        )
        db_session.add_all([b1, b2])
        await db_session.flush()

        from unittest.mock import patch
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _mock_session():
            yield db_session

        with patch("app.modules.marketing.broadcast.async_session_factory", side_effect=_mock_session):
            result = await get_last_broadcast_to_segment("234t", "all_customers")
        assert result is not None
        # SQLite strips tz info — compare naive datetimes
        r = result.replace(tzinfo=None) if result.tzinfo else result
        expected = b2.completed_at.replace(tzinfo=None) if b2.completed_at.tzinfo else b2.completed_at
        assert r == expected

    @pytest.mark.asyncio
    async def test_ignores_different_segment(self, db_session: AsyncSession):
        now = datetime.now(tz=timezone.utc)
        b = Broadcast(
            tenant_id="t1", trader_phone="234t", segment="vip",
            message_text="VIP only", total_recipients=5, sent_count=5,
            status=BroadcastStatus.SENT, completed_at=now,
        )
        db_session.add(b)
        await db_session.flush()

        from unittest.mock import patch
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _mock_session():
            yield db_session

        with patch("app.modules.marketing.broadcast.async_session_factory", side_effect=_mock_session):
            result = await get_last_broadcast_to_segment("234t", "all_customers")
        assert result is None

    @pytest.mark.asyncio
    async def test_ignores_draft_broadcasts(self, db_session: AsyncSession):
        now = datetime.now(tz=timezone.utc)
        b = Broadcast(
            tenant_id="t1", trader_phone="234t", segment="all_customers",
            message_text="Draft", total_recipients=5, sent_count=0,
            status=BroadcastStatus.DRAFT, completed_at=None,
        )
        db_session.add(b)
        await db_session.flush()

        from unittest.mock import patch
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _mock_session():
            yield db_session

        with patch("app.modules.marketing.broadcast.async_session_factory", side_effect=_mock_session):
            result = await get_last_broadcast_to_segment("234t", "all_customers")
        assert result is None
