"""
app/modules/orders/repository.py

Data-access layer for Order and OrderItem entities.
All methods are keyword-argument only (after self) to prevent
positional ordering bugs at call sites.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

    async def create_order(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        customer_id: str | None = None,
        amount: Decimal | None = None,
        currency: str = "NGN",
    ) -> Order:
        """Insert a new INQUIRY order and flush to obtain the PK."""
        order = Order(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            customer_id=customer_id,
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
