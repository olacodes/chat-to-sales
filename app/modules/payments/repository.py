"""
app/modules/payments/repository.py

Data-access layer for the Payment entity.  All public methods are async and
keyword-argument only (after self) to prevent positional ordering bugs.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.orders.models import Order
from app.modules.payments.models import Payment, PaymentStatus

logger = get_logger(__name__)

# Statuses that mean "payment is still relevant / not replaceable"
_ACTIVE_STATUSES = frozenset({PaymentStatus.PENDING, PaymentStatus.SUCCESS})


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Reads ─────────────────────────────────────────────────────────────────

    async def get_by_id(
        self,
        *,
        payment_id: str,
        tenant_id: str | None = None,
    ) -> Payment | None:
        stmt = select(Payment).where(Payment.id == payment_id)
        if tenant_id:
            stmt = stmt.where(Payment.tenant_id == tenant_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_reference(self, *, reference: str) -> Payment | None:
        """
        Look up by provider-assigned reference.

        Intentionally NOT tenant-scoped: Paystack webhooks do not carry
        tenant context — the reference itself is globally unique.
        """
        result = await self._session.execute(
            select(Payment).where(Payment.reference == reference)
        )
        return result.scalar_one_or_none()

    async def get_active_for_order(
        self,
        *,
        order_id: str,
        tenant_id: str,
    ) -> Payment | None:
        """
        Return any PENDING or SUCCESS payment for an order.

        Used by create_payment_for_order to prevent duplicate payment attempts.
        """
        result = await self._session.execute(
            select(Payment)
            .where(
                Payment.order_id == order_id,
                Payment.tenant_id == tenant_id,
                Payment.status.in_([s.value for s in _ACTIVE_STATUSES]),
            )
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ── Writes ────────────────────────────────────────────────────────────────

    async def create_payment(
        self,
        *,
        tenant_id: str,
        order_id: str,
        reference: str,
        amount: Decimal,
        currency: str = "NGN",
        provider: str = "paystack",
        payment_link: str | None = None,
    ) -> Payment:
        payment = Payment(
            tenant_id=tenant_id,
            order_id=order_id,
            reference=reference,
            amount=amount,
            currency=currency,
            status=PaymentStatus.PENDING,
            provider=provider,
            payment_link=payment_link,
        )
        self._session.add(payment)
        await self._session.flush()
        logger.debug(
            "Payment created id=%s order=%s reference=%s",
            payment.id,
            order_id,
            reference,
        )
        return payment

    async def update_status(self, *, payment: Payment, status: str) -> Payment:
        """Persist a status change and flush."""
        payment.status = status
        self._session.add(payment)
        await self._session.flush()
        return payment

    async def list_payments(
        self,
        *,
        tenant_id: str,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[tuple[Payment, str, Decimal | None]], int]:
        """
        Return a page of (Payment, order_state, order_amount) tuples and a
        total count, joined with orders in a single query — no N+1.
        """
        filters = [Payment.tenant_id == tenant_id]
        if status is not None:
            filters.append(Payment.status == status)

        data_stmt = (
            select(
                Payment,
                Order.state.label("order_state"),
                Order.amount.label("order_amount"),
            )
            .join(Order, Payment.order_id == Order.id)
            .where(*filters)
            .order_by(Payment.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(data_stmt)).all()
        results = [(row[0], row[1], row[2]) for row in rows]

        count_stmt = select(func.count()).select_from(Payment).where(*filters)
        total: int = (await self._session.execute(count_stmt)).scalar_one()

        return results, total
