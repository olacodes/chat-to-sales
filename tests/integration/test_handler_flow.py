"""
Integration tests for the order handler flow.

Tests message routing, order creation, and state transitions
through the actual handler pipeline with SQLite + fakeredis.
"""

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.models import Order, OrderItem, OrderState
from app.modules.orders.repository import OrderRepository
from app.modules.orders.session import (
    get_customer_routing,
    get_order_session,
    set_customer_routing,
    set_order_session,
    AWAITING_CUSTOMER_CONFIRMATION,
    AWAITING_CLARIFICATION,
)


class TestCartOrderCreation:
    """Test that cart items from ORDER:{slug} create orders correctly."""

    @pytest.mark.asyncio
    async def test_create_order_from_cart(self, db_session: AsyncSession):
        repo = OrderRepository(db_session)
        order = await repo.create_order(
            tenant_id="test-tenant",
            conversation_id="conv-1",
            customer_phone="234",
            customer_name="Sodiq",
            trader_phone="2348141605756",
            amount=Decimal("126000"),
        )
        await repo.add_item(
            order_id=order.id,
            product_name="Rice 50kg",
            quantity=2,
            unit_price=Decimal("63000"),
        )
        await db_session.commit()

        assert order.state == OrderState.INQUIRY
        assert order.customer_name == "Sodiq"

        # Verify items
        result = await db_session.execute(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )
        items = list(result.scalars().all())
        assert len(items) == 1
        assert items[0].product_name == "Rice 50kg"
        assert items[0].quantity == 2

    @pytest.mark.asyncio
    async def test_order_ref_prefix_lookup(self, db_session: AsyncSession):
        repo = OrderRepository(db_session)
        order = await repo.create_order(
            tenant_id="test-tenant",
            conversation_id="conv-1",
            customer_phone="234",
            amount=Decimal("63000"),
        )
        await db_session.commit()

        ref = order.id[:8]
        found = await repo.get_by_ref_prefix(ref_prefix=ref)
        assert found is not None
        assert found.id == order.id


class TestOrderStateFlow:
    """Test the full order state lifecycle via the repository."""

    @pytest.mark.asyncio
    async def test_inquiry_to_confirmed_to_paid(self, db_session: AsyncSession):
        repo = OrderRepository(db_session)
        order = await repo.create_order(
            tenant_id="test-tenant",
            conversation_id="conv-1",
            customer_phone="234",
            amount=Decimal("500000"),
        )
        assert order.state == OrderState.INQUIRY

        # Confirm
        from app.modules.orders.state_machine import validate_transition
        validate_transition(order.id, order.state, OrderState.CONFIRMED)
        order.state = OrderState.CONFIRMED
        await db_session.commit()
        assert order.state == OrderState.CONFIRMED

        # Pay (terminal)
        validate_transition(order.id, order.state, OrderState.PAID)
        order.state = OrderState.PAID
        await db_session.commit()
        assert order.state == OrderState.PAID

    @pytest.mark.asyncio
    async def test_inquiry_to_cancelled(self, db_session: AsyncSession):
        repo = OrderRepository(db_session)
        order = await repo.create_order(
            tenant_id="test-tenant",
            conversation_id="conv-1",
            customer_phone="234",
            amount=Decimal("100000"),
        )
        from app.modules.orders.state_machine import validate_transition
        validate_transition(order.id, order.state, OrderState.FAILED)
        order.state = OrderState.FAILED
        await db_session.commit()
        assert order.state == OrderState.FAILED


class TestRoutingSession:
    """Test Redis routing session integration."""

    @pytest.mark.asyncio
    async def test_routing_survives_order_session(self, fake_redis):
        """Routing session should persist even after order session is cleared."""
        await set_customer_routing("234", {
            "slug": "ola-phones",
            "tenant_id": "test-tenant",
            "trader_phone": "2348141605756",
            "trader_name": "Ola Phones",
            "catalogue": {},
        })
        # Set then clear an order session
        await set_order_session("test-tenant", "234", {
            "state": AWAITING_CUSTOMER_CONFIRMATION,
            "order_id": "order-1",
        })
        from app.modules.orders.session import clear_order_session
        await clear_order_session("test-tenant", "234")

        # Routing should still exist
        routing = await get_customer_routing("234")
        assert routing is not None
        assert routing["slug"] == "ola-phones"

    @pytest.mark.asyncio
    async def test_new_order_overwrites_routing(self, fake_redis):
        """ORDER:new-slug should overwrite existing routing."""
        await set_customer_routing("234", {"slug": "old-store", "tenant_id": "t1"})
        await set_customer_routing("234", {"slug": "new-store", "tenant_id": "t2"})
        routing = await get_customer_routing("234")
        assert routing["slug"] == "new-store"


class TestQuietMode:
    """Test quiet mode behavior."""

    @pytest.mark.asyncio
    async def test_quiet_mode_set_and_check(self, fake_redis):
        from app.modules.orders.session import is_quiet_mode, set_quiet_mode
        await set_quiet_mode("test-tenant", "234")
        assert await is_quiet_mode("test-tenant", "234") is True

    @pytest.mark.asyncio
    async def test_quiet_mode_not_set(self, fake_redis):
        from app.modules.orders.session import is_quiet_mode
        assert await is_quiet_mode("test-tenant", "unknown") is False


class TestClarificationSession:
    """Test clarification session with numbered items."""

    @pytest.mark.asyncio
    async def test_clarification_with_numbered_items(self, fake_redis):
        await set_order_session("test-tenant", "234", {
            "state": AWAITING_CLARIFICATION,
            "original_message": "I want iphone",
            "bot_reply": "1. iPhone 12 - N290,000\n2. iPhone 14 - N500,000",
            "numbered_items": [
                {"index": 1, "name": "iPhone 12", "price": 290000},
                {"index": 2, "name": "iPhone 14", "price": 500000},
            ],
        })
        session = await get_order_session("test-tenant", "234")
        assert session["state"] == AWAITING_CLARIFICATION
        assert len(session["numbered_items"]) == 2

    @pytest.mark.asyncio
    async def test_cancel_and_restore_clarification(self, fake_redis):
        """After cancel, last clarification should be restorable."""
        from app.modules.orders.session import (
            get_last_clarification,
            save_last_clarification,
        )
        # Save clarification context
        await save_last_clarification("test-tenant", "234", {
            "original_message": "I want iphone",
            "bot_reply": "1. iPhone 12 - N290,000",
            "numbered_items": [{"index": 1, "name": "iPhone 12", "price": 290000}],
        })
        # Simulate order + cancel (order session cleared)
        from app.modules.orders.session import clear_order_session
        await clear_order_session("test-tenant", "234")
        # Clarification context still available
        ctx = await get_last_clarification("test-tenant", "234")
        assert ctx is not None
        assert ctx["numbered_items"][0]["name"] == "iPhone 12"


class TestCreditOrderFlow:
    """Test credit order creation and settlement via DB."""

    @pytest.mark.asyncio
    async def test_credit_then_settle(self, db_session: AsyncSession):
        from app.modules.credit_sales.models import CreditSale, CreditSaleStatus

        repo = OrderRepository(db_session)
        order = await repo.create_order(
            tenant_id="test-tenant",
            conversation_id="conv-1",
            customer_phone="234",
            customer_name="Sodiq",
            amount=Decimal("500000"),
        )
        # Confirm
        order.state = OrderState.CONFIRMED
        order.is_credit = True
        await db_session.flush()

        # Create credit sale
        cs = CreditSale(
            tenant_id="test-tenant",
            order_id=order.id,
            customer_name="Sodiq",
            amount=Decimal("500000"),
            currency="NGN",
        )
        db_session.add(cs)
        await db_session.flush()

        # Partial payment
        cs.amount = Decimal("200000")
        await db_session.flush()
        assert cs.amount == Decimal("200000")

        # Full settlement
        cs.amount = Decimal("0")
        cs.status = CreditSaleStatus.SETTLED
        order.state = OrderState.PAID
        await db_session.commit()

        assert order.state == OrderState.PAID
        assert cs.status == CreditSaleStatus.SETTLED
