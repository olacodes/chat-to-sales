"""
Service tests for the order lifecycle.

Tests order state transitions via the repository and state machine.
"""

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.models import Order, OrderItem, OrderState
from app.modules.orders.repository import OrderRepository
from app.modules.orders.state_machine import InvalidTransitionError, validate_transition


class TestCreateOrder:
    @pytest.mark.asyncio
    async def test_create_inquiry_order(self, db_session: AsyncSession):
        repo = OrderRepository(db_session)
        order = await repo.create_order(
            tenant_id="test-tenant",
            conversation_id="conv-1",
            customer_phone="2348166041471",
            customer_name="Sodiq Olatunde",
            trader_phone="2348141605756",
            amount=Decimal("500000"),
        )
        assert order.state == OrderState.INQUIRY
        assert order.customer_phone == "2348166041471"
        assert order.customer_name == "Sodiq Olatunde"
        assert order.amount == Decimal("500000")

    @pytest.mark.asyncio
    async def test_order_has_uuid_id(self, db_session: AsyncSession):
        repo = OrderRepository(db_session)
        order = await repo.create_order(
            tenant_id="t", conversation_id="c",
        )
        assert order.id is not None
        assert len(order.id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_order_preserves_customer_name(self, sample_order: Order):
        assert sample_order.customer_name == "Sodiq Olatunde"

    @pytest.mark.asyncio
    async def test_order_default_currency(self, db_session: AsyncSession):
        repo = OrderRepository(db_session)
        order = await repo.create_order(
            tenant_id="t", conversation_id="c",
        )
        assert order.currency == "NGN"


class TestOrderLookup:
    @pytest.mark.asyncio
    async def test_get_by_ref_prefix(self, db_session: AsyncSession, sample_order: Order):
        repo = OrderRepository(db_session)
        ref = sample_order.id[:8]
        found = await repo.get_by_ref_prefix(ref_prefix=ref)
        assert found is not None
        assert found.id == sample_order.id

    @pytest.mark.asyncio
    async def test_get_by_ref_prefix_not_found(self, db_session: AsyncSession):
        repo = OrderRepository(db_session)
        found = await repo.get_by_ref_prefix(ref_prefix="00000000")
        assert found is None

    @pytest.mark.asyncio
    async def test_get_open_order_by_customer_phone(self, db_session: AsyncSession, sample_order: Order):
        repo = OrderRepository(db_session)
        found = await repo.get_open_order_by_customer_phone(
            customer_phone="2348166041471",
            tenant_id="test-tenant",
        )
        assert found is not None
        assert found.id == sample_order.id

    @pytest.mark.asyncio
    async def test_no_open_order_for_unknown_customer(self, db_session: AsyncSession):
        repo = OrderRepository(db_session)
        found = await repo.get_open_order_by_customer_phone(
            customer_phone="0000000000",
            tenant_id="test-tenant",
        )
        assert found is None


class TestOrderTransitions:
    @pytest.mark.asyncio
    async def test_confirm_order(self, db_session: AsyncSession, sample_order: Order):
        validate_transition(sample_order.id, sample_order.state, OrderState.CONFIRMED)
        sample_order.state = OrderState.CONFIRMED
        await db_session.flush()
        assert sample_order.state == OrderState.CONFIRMED

    @pytest.mark.asyncio
    async def test_pay_confirmed_order(self, db_session: AsyncSession, confirmed_order: Order):
        validate_transition(confirmed_order.id, confirmed_order.state, OrderState.PAID)
        confirmed_order.state = OrderState.PAID
        await db_session.flush()
        assert confirmed_order.state == OrderState.PAID

    @pytest.mark.asyncio
    async def test_cancel_inquiry(self, db_session: AsyncSession, sample_order: Order):
        validate_transition(sample_order.id, sample_order.state, OrderState.FAILED)
        sample_order.state = OrderState.FAILED
        await db_session.flush()
        assert sample_order.state == OrderState.FAILED

    @pytest.mark.asyncio
    async def test_cancel_confirmed(self, db_session: AsyncSession, confirmed_order: Order):
        validate_transition(confirmed_order.id, confirmed_order.state, OrderState.FAILED)
        confirmed_order.state = OrderState.FAILED
        await db_session.flush()
        assert confirmed_order.state == OrderState.FAILED

    @pytest.mark.asyncio
    async def test_cannot_pay_inquiry(self, sample_order: Order):
        with pytest.raises(InvalidTransitionError):
            validate_transition(sample_order.id, OrderState.INQUIRY, OrderState.PAID)

    @pytest.mark.asyncio
    async def test_cannot_modify_paid(self, db_session: AsyncSession, confirmed_order: Order):
        confirmed_order.state = OrderState.PAID
        await db_session.flush()
        with pytest.raises(InvalidTransitionError):
            validate_transition(confirmed_order.id, OrderState.PAID, OrderState.FAILED)


class TestCreditOrder:
    @pytest.mark.asyncio
    async def test_mark_order_as_credit(self, db_session: AsyncSession, confirmed_order: Order):
        confirmed_order.is_credit = True
        await db_session.flush()
        assert confirmed_order.is_credit is True

    @pytest.mark.asyncio
    async def test_order_default_not_credit(self, sample_order: Order):
        assert sample_order.is_credit is False
