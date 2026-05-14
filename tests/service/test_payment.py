"""
Service tests for payment detection and processing.

Tests that payment-related intents find the right orders and
produce the right outcomes.
"""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.models import Order, OrderState
from app.modules.orders.repository import OrderRepository


class TestPaymentOrderLookup:
    @pytest.mark.asyncio
    async def test_finds_confirmed_order_for_customer(self, db_session: AsyncSession, confirmed_order: Order):
        """Payment detection should find the customer's CONFIRMED order."""
        repo = OrderRepository(db_session)
        found = await repo.get_open_order_by_customer_phone(
            customer_phone="2348166041471",
            tenant_id="test-tenant",
        )
        assert found is not None
        assert found.state == OrderState.CONFIRMED

    @pytest.mark.asyncio
    async def test_no_match_for_inquiry_order(self, db_session: AsyncSession, sample_order: Order):
        """Payment on an INQUIRY order — order exists but is not CONFIRMED."""
        repo = OrderRepository(db_session)
        found = await repo.get_open_order_by_customer_phone(
            customer_phone="2348166041471",
            tenant_id="test-tenant",
        )
        # Open order found, but it's INQUIRY not CONFIRMED — payment handler should check state
        assert found is not None
        assert found.state == OrderState.INQUIRY

    @pytest.mark.asyncio
    async def test_no_order_for_unknown_customer(self, db_session: AsyncSession):
        """Payment with no order at all."""
        repo = OrderRepository(db_session)
        found = await repo.get_open_order_by_customer_phone(
            customer_phone="0000000000",
            tenant_id="test-tenant",
        )
        assert found is None

    @pytest.mark.asyncio
    async def test_paid_order_not_found_as_open(self, db_session: AsyncSession, confirmed_order: Order):
        """Once paid, the order should not appear as open."""
        confirmed_order.state = OrderState.PAID
        await db_session.flush()

        repo = OrderRepository(db_session)
        found = await repo.get_open_order_by_customer_phone(
            customer_phone="2348166041471",
            tenant_id="test-tenant",
        )
        assert found is None


class TestPaymentTransition:
    @pytest.mark.asyncio
    async def test_payrcvd_transitions_to_paid(self, db_session: AsyncSession, confirmed_order: Order):
        """PAYRCVD should transition CONFIRMED → PAID."""
        from app.modules.orders.state_machine import validate_transition
        validate_transition(confirmed_order.id, OrderState.CONFIRMED, OrderState.PAID)
        confirmed_order.state = OrderState.PAID
        await db_session.flush()
        assert confirmed_order.state == OrderState.PAID

    @pytest.mark.asyncio
    async def test_payrcvd_on_inquiry_fails(self, sample_order: Order):
        """Cannot mark an INQUIRY as paid."""
        from app.modules.orders.state_machine import InvalidTransitionError, validate_transition
        with pytest.raises(InvalidTransitionError):
            validate_transition(sample_order.id, OrderState.INQUIRY, OrderState.PAID)
