"""
Service tests for customer→trader routing.

Tests Redis routing session, persistent DB routing, and TTL behavior.
"""

import pytest

from app.modules.orders.session import (
    _CUSTOMER_ROUTING_TTL,
    clear_customer_routing,
    get_customer_routing,
    set_customer_routing,
)


class TestRedisRouting:
    @pytest.mark.asyncio
    async def test_set_and_get_routing(self, fake_redis):
        await set_customer_routing("234", {
            "slug": "ola-phones",
            "tenant_id": "tenant-1",
            "trader_phone": "2348141605756",
            "trader_name": "Ola Phones",
            "catalogue": {"iPhone 14": 500000},
        })
        routing = await get_customer_routing("234")
        assert routing is not None
        assert routing["slug"] == "ola-phones"
        assert routing["trader_name"] == "Ola Phones"

    @pytest.mark.asyncio
    async def test_routing_not_found(self, fake_redis):
        routing = await get_customer_routing("unknown")
        assert routing is None

    @pytest.mark.asyncio
    async def test_clear_routing(self, fake_redis):
        await set_customer_routing("234", {"slug": "test"})
        await clear_customer_routing("234")
        routing = await get_customer_routing("234")
        assert routing is None

    @pytest.mark.asyncio
    async def test_new_slug_overwrites_routing(self, fake_redis):
        await set_customer_routing("234", {
            "slug": "old-store",
            "tenant_id": "tenant-1",
        })
        await set_customer_routing("234", {
            "slug": "new-store",
            "tenant_id": "tenant-2",
        })
        routing = await get_customer_routing("234")
        assert routing["slug"] == "new-store"
        assert routing["tenant_id"] == "tenant-2"

    def test_routing_ttl_is_7_days(self):
        assert _CUSTOMER_ROUTING_TTL == 7 * 24 * 60 * 60


class TestPersistentRouting:
    @pytest.mark.asyncio
    async def test_upsert_creates_new(self, db_session):
        from app.modules.orders.customer_routing import CustomerRoutingRepository
        repo = CustomerRoutingRepository(db_session)
        await repo.upsert(
            customer_phone="234",
            trader_phone="2348141605756",
            store_slug="ola-phones",
            tenant_id="tenant-1",
        )
        await db_session.flush()
        found = await repo.get_by_customer("234")
        assert found is not None
        assert found.store_slug == "ola-phones"

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, db_session):
        from app.modules.orders.customer_routing import CustomerRoutingRepository
        repo = CustomerRoutingRepository(db_session)
        await repo.upsert(
            customer_phone="234",
            trader_phone="phone1",
            store_slug="old-store",
            tenant_id="tenant-1",
        )
        await db_session.flush()
        await repo.upsert(
            customer_phone="234",
            trader_phone="phone2",
            store_slug="new-store",
            tenant_id="tenant-2",
        )
        await db_session.flush()
        found = await repo.get_by_customer("234")
        assert found.store_slug == "new-store"
        assert found.tenant_id == "tenant-2"

    @pytest.mark.asyncio
    async def test_get_unknown_customer_returns_none(self, db_session):
        from app.modules.orders.customer_routing import CustomerRoutingRepository
        repo = CustomerRoutingRepository(db_session)
        found = await repo.get_by_customer("unknown")
        assert found is None
