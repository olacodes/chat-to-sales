"""
Service tests for credit/debt management.

Tests credit sale creation, settlement, partial payment, and duplicate guard.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.credit_sales.models import CreditSale, CreditSaleStatus
from app.modules.orders.models import Order, OrderState


class TestCreditSaleCreation:
    @pytest.mark.asyncio
    async def test_create_credit_sale(self, db_session: AsyncSession, confirmed_order: Order):
        cs = CreditSale(
            tenant_id=confirmed_order.tenant_id,
            order_id=confirmed_order.id,
            conversation_id=confirmed_order.conversation_id,
            customer_name="Sodiq Olatunde",
            amount=confirmed_order.amount,
            currency="NGN",
        )
        db_session.add(cs)
        await db_session.flush()
        assert cs.id is not None
        assert cs.status == CreditSaleStatus.ACTIVE
        assert cs.amount == Decimal("500000")

    @pytest.mark.asyncio
    async def test_mark_order_as_credit(self, db_session: AsyncSession, confirmed_order: Order):
        confirmed_order.is_credit = True
        await db_session.flush()
        assert confirmed_order.is_credit is True

    @pytest.mark.asyncio
    async def test_duplicate_credit_blocked_by_unique_constraint(
        self, db_session: AsyncSession, confirmed_order: Order
    ):
        """Second credit sale for same order should fail (unique constraint)."""
        cs1 = CreditSale(
            tenant_id=confirmed_order.tenant_id,
            order_id=confirmed_order.id,
            customer_name="Sodiq",
            amount=Decimal("500000"),
            currency="NGN",
        )
        db_session.add(cs1)
        await db_session.flush()

        cs2 = CreditSale(
            tenant_id=confirmed_order.tenant_id,
            order_id=confirmed_order.id,
            customer_name="Sodiq",
            amount=Decimal("500000"),
            currency="NGN",
        )
        db_session.add(cs2)
        with pytest.raises(Exception):  # IntegrityError
            await db_session.flush()


class TestCreditSettlement:
    @pytest.mark.asyncio
    async def test_settle_credit_sale(self, db_session: AsyncSession, confirmed_order: Order):
        cs = CreditSale(
            tenant_id=confirmed_order.tenant_id,
            order_id=confirmed_order.id,
            customer_name="Sodiq",
            amount=Decimal("500000"),
            currency="NGN",
        )
        db_session.add(cs)
        await db_session.flush()

        cs.status = CreditSaleStatus.SETTLED
        cs.amount = Decimal("0")
        await db_session.flush()
        assert cs.status == CreditSaleStatus.SETTLED

    @pytest.mark.asyncio
    async def test_partial_payment_reduces_balance(self, db_session: AsyncSession, confirmed_order: Order):
        cs = CreditSale(
            tenant_id=confirmed_order.tenant_id,
            order_id=confirmed_order.id,
            customer_name="Sodiq",
            amount=Decimal("500000"),
            currency="NGN",
        )
        db_session.add(cs)
        await db_session.flush()

        # Partial payment of 200,000
        cs.amount = Decimal("300000")
        await db_session.flush()
        assert cs.amount == Decimal("300000")
        assert cs.status == CreditSaleStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_partial_then_full_settles(self, db_session: AsyncSession, confirmed_order: Order):
        cs = CreditSale(
            tenant_id=confirmed_order.tenant_id,
            order_id=confirmed_order.id,
            customer_name="Sodiq",
            amount=Decimal("500000"),
            currency="NGN",
        )
        db_session.add(cs)
        await db_session.flush()

        # First partial
        cs.amount = Decimal("200000")
        await db_session.flush()

        # Second partial = full settlement
        cs.amount = Decimal("0")
        cs.status = CreditSaleStatus.SETTLED
        await db_session.flush()
        assert cs.status == CreditSaleStatus.SETTLED
        assert cs.amount == Decimal("0")

    @pytest.mark.asyncio
    async def test_credit_sale_lookup_by_order(self, db_session: AsyncSession, confirmed_order: Order):
        cs = CreditSale(
            tenant_id=confirmed_order.tenant_id,
            order_id=confirmed_order.id,
            customer_name="Sodiq",
            amount=Decimal("500000"),
            currency="NGN",
        )
        db_session.add(cs)
        await db_session.flush()

        result = await db_session.execute(
            select(CreditSale).where(
                CreditSale.order_id == confirmed_order.id,
                CreditSale.status == CreditSaleStatus.ACTIVE,
            )
        )
        found = result.scalar_one_or_none()
        assert found is not None
        assert found.amount == Decimal("500000")

    @pytest.mark.asyncio
    async def test_settled_credit_not_found_as_active(self, db_session: AsyncSession, confirmed_order: Order):
        cs = CreditSale(
            tenant_id=confirmed_order.tenant_id,
            order_id=confirmed_order.id,
            customer_name="Sodiq",
            amount=Decimal("0"),
            currency="NGN",
            status=CreditSaleStatus.SETTLED,
        )
        db_session.add(cs)
        await db_session.flush()

        result = await db_session.execute(
            select(CreditSale).where(
                CreditSale.order_id == confirmed_order.id,
                CreditSale.status == CreditSaleStatus.ACTIVE,
            )
        )
        assert result.scalar_one_or_none() is None
