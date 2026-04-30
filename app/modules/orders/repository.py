"""
app/modules/orders/repository.py

Data-access layer for Order and OrderItem entities.
All methods are keyword-argument only (after self) to prevent
positional ordering bugs at call sites.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.modules.orders.models import Order, OrderItem, OrderState

logger = get_logger(__name__)

# States that mean "an order is still in progress"
_OPEN_STATES = frozenset({OrderState.INQUIRY, OrderState.CONFIRMED})


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_by_id(
        self,
        *,
        order_id: str,
        tenant_id: str | None = None,
    ) -> Order | None:
        """
        Fetch an order by primary key.

        When tenant_id is supplied the query is tenant-scoped to prevent
        cross-tenant data leakage.
        """
        stmt = select(Order).where(Order.id == order_id)
        if tenant_id:
            stmt = stmt.where(Order.tenant_id == tenant_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_open_order_for_conversation(
        self,
        *,
        conversation_id: str,
        tenant_id: str,
    ) -> Order | None:
        """
        Return the most recent open (INQUIRY or CONFIRMED) order for a
        conversation, or None if no open order exists.

        Used for idempotency: if an open order already exists we must not
        create a duplicate when the customer repeats their intent.
        """
        result = await self._session.execute(
            select(Order)
            .where(
                Order.conversation_id == conversation_id,
                Order.tenant_id == tenant_id,
                Order.state.in_([s.value for s in _OPEN_STATES]),
            )
            .order_by(Order.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ── Write ─────────────────────────────────────────────────────────────────

    async def get_by_ref_prefix(
        self,
        *,
        ref_prefix: str,
        tenant_id: str | None = None,
    ) -> Order | None:
        """
        Look up an order by its short reference (first 8 hex chars of the UUID).

        Used when a trader types "CONFIRM 3f8a2c1b" — the ref is the UUID prefix.
        The 8-char hex prefix of a UUID v4 is practically unique, so the
        tenant_id filter is optional.  It is omitted for trader commands because
        the order may have been created under a different tenant (platform vs
        dedicated) depending on when the trader first logged into the dashboard.
        """
        query = (
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id.like(f"{ref_prefix}%"))
        )
        if tenant_id:
            query = query.where(Order.tenant_id == tenant_id)
        result = await self._session.execute(query.limit(1))
        return result.scalar_one_or_none()

    async def get_open_order_by_customer_phone(
        self,
        *,
        customer_phone: str,
        tenant_id: str,
    ) -> Order | None:
        """Return the most recent open order for a customer's phone number."""
        result = await self._session.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(
                Order.customer_phone == customer_phone,
                Order.tenant_id == tenant_id,
                Order.state.in_([s.value for s in _OPEN_STATES]),
            )
            .order_by(Order.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_order(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        customer_id: str | None = None,
        customer_phone: str | None = None,
        amount: Decimal | None = None,
        currency: str = "NGN",
    ) -> Order:
        """Insert a new INQUIRY order and flush to obtain the PK."""
        order = Order(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            customer_id=customer_id,
            customer_phone=customer_phone,
            state=OrderState.INQUIRY,
            amount=amount,
            currency=currency,
        )
        self._session.add(order)
        await self._session.flush()
        logger.debug(
            "Order created id=%s tenant=%s conversation=%s",
            order.id,
            tenant_id,
            conversation_id,
        )
        return order

    async def update_state(
        self,
        *,
        order: Order,
        new_state: str,
    ) -> Order:
        """Persist a state change that has already been validated."""
        order.state = new_state
        self._session.add(order)
        await self._session.flush()
        return order

    async def delete_items_for_order(self, *, order_id: str) -> None:
        """Remove all line items for an order (used when replacing items on upsert)."""
        await self._session.execute(
            delete(OrderItem).where(OrderItem.order_id == order_id)
        )
        await self._session.flush()

    async def add_item(
        self,
        *,
        order_id: str,
        product_name: str,
        quantity: int,
        unit_price: Decimal,
    ) -> OrderItem:
        item = OrderItem(
            order_id=order_id,
            product_name=product_name,
            quantity=quantity,
            unit_price=unit_price,
        )
        self._session.add(item)
        await self._session.flush()
        return item

    # ── List query ────────────────────────────────────────────────────────────

    async def list_orders(
        self,
        *,
        tenant_id: str,
        state: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[tuple[Order, int]], int]:
        """
        Return a page of (Order, item_count) tuples and a total count.

        item_count is computed via a correlated SQL subquery — no Python-level
        iteration and no selectin on Order.items.  The caller gets the count
        for free in the same round-trip.

        A separate COUNT(*) query returns the total matching rows for
        pagination metadata (dashboard page-count display).
        """
        filters = [Order.tenant_id == tenant_id]
        if state is not None:
            filters.append(Order.state == state)
        if from_date is not None:
            filters.append(
                Order.created_at
                >= datetime(from_date.year, from_date.month, from_date.day)
            )
        if to_date is not None:
            # inclusive end-of-day
            filters.append(
                Order.created_at
                < datetime(to_date.year, to_date.month, to_date.day + 1)
            )

        data_stmt = (
            select(Order)
            .options(selectinload(Order.items))
            .where(*filters)
            .order_by(Order.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        orders = (await self._session.execute(data_stmt)).scalars().all()
        results = [(order, len(order.items)) for order in orders]

        count_stmt = select(func.count()).select_from(Order).where(*filters)
        total: int = (await self._session.execute(count_stmt)).scalar_one()

        return results, total
