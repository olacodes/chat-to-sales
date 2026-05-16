"""
Service tests for CustomerListService — upsert, opt-out, segments.
"""

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketing.customer_list import CustomerListService
from app.modules.marketing.models import CustomerListEntry


class TestUpsertCustomer:
    @pytest.mark.asyncio
    async def test_first_upsert_creates_entry(self, db_session: AsyncSession):
        svc = CustomerListService(db_session)
        entry = await svc.upsert_customer(
            trader_phone="234trader",
            tenant_id="t1",
            customer_phone="234customer",
            customer_name="Bimpe",
            order_amount=Decimal("5000"),
        )
        assert entry.customer_phone == "234customer"
        assert entry.customer_name == "Bimpe"
        assert entry.total_orders == 1
        assert entry.total_spend == Decimal("5000")
        assert entry.first_order_date is not None
        assert entry.last_order_date is not None

    @pytest.mark.asyncio
    async def test_second_upsert_updates_aggregates(self, db_session: AsyncSession):
        svc = CustomerListService(db_session)
        await svc.upsert_customer(
            trader_phone="234trader", tenant_id="t1",
            customer_phone="234customer", order_amount=Decimal("5000"),
        )
        entry = await svc.upsert_customer(
            trader_phone="234trader", tenant_id="t1",
            customer_phone="234customer", order_amount=Decimal("3000"),
        )
        assert entry.total_orders == 2
        assert entry.total_spend == Decimal("8000")

    @pytest.mark.asyncio
    async def test_upsert_fills_name_if_missing(self, db_session: AsyncSession):
        svc = CustomerListService(db_session)
        await svc.upsert_customer(
            trader_phone="234t", tenant_id="t1",
            customer_phone="234c", customer_name=None,
        )
        entry = await svc.upsert_customer(
            trader_phone="234t", tenant_id="t1",
            customer_phone="234c", customer_name="Ade",
        )
        assert entry.customer_name == "Ade"

    @pytest.mark.asyncio
    async def test_upsert_does_not_overwrite_name(self, db_session: AsyncSession):
        svc = CustomerListService(db_session)
        await svc.upsert_customer(
            trader_phone="234t", tenant_id="t1",
            customer_phone="234c", customer_name="Bimpe",
        )
        entry = await svc.upsert_customer(
            trader_phone="234t", tenant_id="t1",
            customer_phone="234c", customer_name="Ade",
        )
        assert entry.customer_name == "Bimpe"  # keeps first name


class TestOptOut:
    @pytest.mark.asyncio
    async def test_opt_out_marks_customer(self, db_session: AsyncSession):
        svc = CustomerListService(db_session)
        await svc.upsert_customer(
            trader_phone="234t", tenant_id="t1", customer_phone="234c",
        )
        result = await svc.opt_out("234t", "234c")
        assert result is True

    @pytest.mark.asyncio
    async def test_opt_out_not_found(self, db_session: AsyncSession):
        svc = CustomerListService(db_session)
        result = await svc.opt_out("234t", "nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_opt_out_already_opted_out(self, db_session: AsyncSession):
        svc = CustomerListService(db_session)
        await svc.upsert_customer(
            trader_phone="234t", tenant_id="t1", customer_phone="234c",
        )
        await svc.opt_out("234t", "234c")
        result = await svc.opt_out("234t", "234c")
        assert result is False  # already opted out

    @pytest.mark.asyncio
    async def test_opted_out_excluded_from_list(self, db_session: AsyncSession):
        svc = CustomerListService(db_session)
        await svc.upsert_customer(
            trader_phone="234t", tenant_id="t1", customer_phone="234c1",
        )
        await svc.upsert_customer(
            trader_phone="234t", tenant_id="t1", customer_phone="234c2",
        )
        await svc.opt_out("234t", "234c1")
        customers = await svc.get_customers_for_trader("234t")
        phones = [c.customer_phone for c in customers]
        assert "234c1" not in phones
        assert "234c2" in phones


class TestSegmentCounts:
    @pytest.mark.asyncio
    async def test_empty_trader(self, db_session: AsyncSession):
        svc = CustomerListService(db_session)
        counts = await svc.get_segment_counts("234nobody")
        assert counts["all_customers"] == 0

    @pytest.mark.asyncio
    async def test_basic_counts(self, db_session: AsyncSession):
        svc = CustomerListService(db_session)
        # VIP: 5+ orders
        e1 = CustomerListEntry(
            tenant_id="t1", trader_phone="234t", customer_phone="c1",
            total_orders=6, total_spend=Decimal("300000"),
        )
        # Repeat: 2-4 orders
        e2 = CustomerListEntry(
            tenant_id="t1", trader_phone="234t", customer_phone="c2",
            total_orders=3, total_spend=Decimal("15000"),
        )
        # Paid once
        e3 = CustomerListEntry(
            tenant_id="t1", trader_phone="234t", customer_phone="c3",
            total_orders=1, total_spend=Decimal("5000"),
        )
        db_session.add_all([e1, e2, e3])
        await db_session.flush()

        counts = await svc.get_segment_counts("234t")
        assert counts["all_customers"] == 3

    @pytest.mark.asyncio
    async def test_get_customers_by_segment_all(self, db_session: AsyncSession):
        svc = CustomerListService(db_session)
        e1 = CustomerListEntry(
            tenant_id="t1", trader_phone="234t", customer_phone="c1",
            total_orders=1, total_spend=Decimal("5000"),
        )
        e2 = CustomerListEntry(
            tenant_id="t1", trader_phone="234t", customer_phone="c2",
            total_orders=2, total_spend=Decimal("10000"),
        )
        db_session.add_all([e1, e2])
        await db_session.flush()

        all_custs = await svc.get_customers_by_segment("234t", "all_customers")
        assert len(all_custs) == 2

    @pytest.mark.asyncio
    async def test_get_customers_by_stored_segment(self, db_session: AsyncSession):
        svc = CustomerListService(db_session)
        e1 = CustomerListEntry(
            tenant_id="t1", trader_phone="234t", customer_phone="c1",
            total_orders=5, total_spend=Decimal("300000"),
            segments=["vip", "weekend"],
        )
        e2 = CustomerListEntry(
            tenant_id="t1", trader_phone="234t", customer_phone="c2",
            total_orders=1, total_spend=Decimal("5000"),
            segments=["paid_once"],
        )
        db_session.add_all([e1, e2])
        await db_session.flush()

        vips = await svc.get_customers_by_segment("234t", "vip")
        assert len(vips) == 1
        assert vips[0].customer_phone == "c1"

        weekenders = await svc.get_customers_by_segment("234t", "weekend")
        assert len(weekenders) == 1

    @pytest.mark.asyncio
    async def test_customer_count(self, db_session: AsyncSession):
        svc = CustomerListService(db_session)
        e1 = CustomerListEntry(
            tenant_id="t1", trader_phone="234t", customer_phone="c1",
            total_orders=1, total_spend=Decimal("1000"),
        )
        e2 = CustomerListEntry(
            tenant_id="t1", trader_phone="234t", customer_phone="c2",
            total_orders=1, total_spend=Decimal("1000"), opted_out=True,
        )
        db_session.add_all([e1, e2])
        await db_session.flush()

        count = await svc.get_customer_count("234t")
        assert count == 1  # opted out excluded
