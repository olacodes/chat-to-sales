"""
app/modules/orders/service.py

OrderService — orchestrates the order lifecycle.

Every state-changing method:
  1. Loads the order (tenant-scoped for safety)
  2. Delegates to the state machine for validation
  3. Persists the new state via the repository
  4. Emits an event on the Redis event bus
  5. Commits the transaction

The caller (HTTP handler or event handler) is free to wrap the call in an
explicit try/except to surface InvalidTransitionError as HTTP 409.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.infra.event_bus import Event, publish_event
from app.modules.orders.models import Order, OrderState
from app.modules.orders.repository import OrderRepository
from app.modules.orders.schemas import OrderCreate, OrderItemCreate, OrderListResponse
from app.modules.orders.state_machine import InvalidTransitionError, validate_transition

logger = get_logger(__name__)

# ── Event names ───────────────────────────────────────────────────────────────
_EVT_CREATED = "order.created"
_EVT_STATE_CHANGED = "order.state_changed"
_EVT_PAID = "order.paid"


class OrderService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = OrderRepository(db)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_or_404(self, order_id: str, tenant_id: str | None = None) -> Order:
        order = await self._repo.get_by_id(order_id=order_id, tenant_id=tenant_id)
        if order is None:
            raise NotFoundError("Order", order_id)
        return order

    async def _transition(self, order: Order, new_state: str) -> Order:
        """
        Validate → persist → emit → return updated order.

        Raises InvalidTransitionError (→ HTTP 409) on bad transitions.
        """
        previous_state = order.state
        try:
            validate_transition(order.id, previous_state, new_state)
        except InvalidTransitionError as exc:
            logger.warning(str(exc))
            raise ConflictError(str(exc)) from exc

        await self._repo.update_state(order=order, new_state=new_state)
        logger.info(
            "Order transition order_id=%s %s → %s",
            order.id,
            previous_state,
            new_state,
        )

        event = Event(
            event_name=_EVT_STATE_CHANGED,
            tenant_id=order.tenant_id,
            payload={
                "order_id": order.id,
                "conversation_id": order.conversation_id,
                "previous_state": previous_state,
                "new_state": new_state,
            },
        )
        await publish_event(event)
        return order

    async def _reload(self, order_id: str) -> Order:
        """Re-query order with eager-loaded items for API serialisation."""
        result = await self._db.execute(
            select(Order)
            .where(Order.id == order_id)
            .options(selectinload(Order.items))
            .execution_options(populate_existing=True)
        )
        return result.scalar_one()

    # ── Event-driven creation ─────────────────────────────────────────────────

    async def create_order_from_conversation(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        customer_id: str | None = None,
    ) -> Order | None:
        """
        Create an INQUIRY order for a conversation.

        Returns None (and does NOT create a duplicate) if an open order
        already exists for that conversation — idempotency guarantee.

        The caller must commit after this returns.
        """
        existing = await self._repo.get_open_order_for_conversation(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
        )
        if existing is not None:
            logger.info(
                "Open order already exists order_id=%s conversation_id=%s — skipping",
                existing.id,
                conversation_id,
            )
            return None

        order = await self._repo.create_order(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            customer_id=customer_id,
        )
        logger.info(
            "Order created order_id=%s tenant=%s conversation=%s",
            order.id,
            tenant_id,
            conversation_id,
        )
        await publish_event(
            Event(
                event_name=_EVT_CREATED,
                tenant_id=tenant_id,
                payload={
                    "order_id": order.id,
                    "conversation_id": conversation_id,
                    "state": OrderState.INQUIRY,
                },
            )
        )
        return order

    # ── HTTP API creation (with items) ────────────────────────────────────────

    async def create_order(self, data: OrderCreate) -> Order:
        """
        Create an order with line items (used by the REST API).

        Computes the total amount from items and sets it on the order.
        """
        existing = await self._repo.get_open_order_for_conversation(
            conversation_id=data.conversation_id,
            tenant_id=data.tenant_id,
        )
        if existing is not None:
            raise ConflictError(
                f"An open order already exists for conversation '{data.conversation_id}'."
            )

        total = (
            sum(item.unit_price * item.quantity for item in data.items)
            if data.items
            else Decimal("0")
        )

        order = await self._repo.create_order(
            tenant_id=data.tenant_id,
            conversation_id=data.conversation_id,
            customer_id=data.customer_id,
            amount=total or None,
            currency=data.currency,
        )

        for item_data in data.items:
            await self._repo.add_item(
                order_id=order.id,
                product_name=item_data.name,
                quantity=item_data.quantity,
                unit_price=item_data.unit_price,
            )

        await self._db.refresh(order)
        await publish_event(
            Event(
                event_name=_EVT_CREATED,
                tenant_id=order.tenant_id,
                payload={
                    "order_id": order.id,
                    "conversation_id": order.conversation_id,
                    "state": OrderState.INQUIRY,
                    "amount": str(order.amount) if order.amount else None,
                    "currency": order.currency,
                },
            )
        )
        await self._db.commit()
        return await self._reload(order.id)

    # ── State transition methods ───────────────────────────────────────────────

    async def get_by_id(self, order_id: str, *, tenant_id: str | None = None) -> Order:
        return await self._get_or_404(order_id, tenant_id)

    async def confirm_order(
        self, order_id: str, *, tenant_id: str | None = None
    ) -> Order:
        order = await self._get_or_404(order_id, tenant_id)
        order = await self._transition(order, OrderState.CONFIRMED)
        await self._db.commit()
        return await self._reload(order.id)

    async def mark_order_paid(
        self, order_id: str, *, tenant_id: str | None = None
    ) -> Order:
        order = await self._get_or_404(order_id, tenant_id)
        order = await self._do_paid_transition(order)
        await self._db.commit()
        return await self._reload(order.id)

    async def _do_paid_transition(self, order: Order) -> Order:
        """
        Core CONFIRMED → PAID logic shared by HTTP and event-handler paths.

        Validates the transition, persists the new state, emits both
        order.state_changed and order.paid events.  Does NOT commit —
        the caller owns the transaction.
        """
        order = await self._transition(order, OrderState.PAID)
        # Emit dedicated payment event for downstream modules
        await publish_event(
            Event(
                event_name=_EVT_PAID,
                tenant_id=order.tenant_id,
                payload={
                    "order_id": order.id,
                    "conversation_id": order.conversation_id,
                    "previous_state": OrderState.CONFIRMED,
                    "new_state": OrderState.PAID,
                    "amount": str(order.amount) if order.amount else None,
                    "currency": order.currency,
                },
            )
        )
        return order

    async def handle_payment_confirmed(
        self, *, order_id: str, tenant_id: str
    ) -> Order | None:
        """
        Transition an order CONFIRMED → PAID after a successful payment event.

        Called by payments/handlers.py inside async_session_factory.begin(),
        so this method must NOT call commit — begin() owns the transaction.

        Returns None (instead of raising) if the order is missing or the
        transition is not applicable, so the event handler can log a warning
        and the listener loop continues.

        Idempotent: if the order is already PAID, returns the order unchanged.
        """
        order = await self._repo.get_by_id(order_id=order_id, tenant_id=tenant_id)
        if order is None:
            logger.warning(
                "handle_payment_confirmed: order not found order_id=%s", order_id
            )
            return None

        if order.state == OrderState.PAID:
            logger.info(
                "handle_payment_confirmed: order already PAID order_id=%s — idempotent",
                order_id,
            )
            return order

        try:
            order = await self._do_paid_transition(order)
        except ConflictError as exc:
            logger.warning(
                "handle_payment_confirmed: cannot transition order_id=%s state=%s: %s",
                order_id,
                order.state,
                exc,
            )
            return None

        return order

    async def complete_order(
        self, order_id: str, *, tenant_id: str | None = None
    ) -> Order:
        order = await self._get_or_404(order_id, tenant_id)
        order = await self._transition(order, OrderState.COMPLETED)
        await self._db.commit()
        return await self._reload(order.id)

    async def fail_order(self, order_id: str, *, tenant_id: str | None = None) -> Order:
        order = await self._get_or_404(order_id, tenant_id)
        order = await self._transition(order, OrderState.FAILED)
        await self._db.commit()
        return await self._reload(order.id)

    async def add_items(
        self,
        order_id: str,
        items: list[OrderItemCreate],
        *,
        tenant_id: str | None = None,
    ) -> Order:
        """
        Append line items to an existing order and recalculate the total.

        Only allowed when the order is in INQUIRY or CONFIRMED state.
        Raises ConflictError for terminal or paid orders.
        """
        order = await self._get_or_404(order_id, tenant_id)
        if order.state not in (OrderState.INQUIRY, OrderState.CONFIRMED):
            raise ConflictError(
                f"Cannot add items to an order in '{order.state}' state."
            )

        for item in items:
            await self._repo.add_item(
                order_id=order.id,
                product_name=item.name,
                quantity=item.quantity,
                unit_price=item.unit_price,
            )

        # Compute total from the request data — avoids touching order.items
        # before the relationship has been reloaded.
        order.amount = sum(item.unit_price * item.quantity for item in items)
        await self._db.flush()
        await self._db.commit()
        return await self._reload(order.id)

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
    ) -> OrderListResponse:
        from app.modules.orders.schemas import OrderListItem

        rows, total = await self._repo.list_orders(
            tenant_id=tenant_id,
            state=state,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset,
        )
        items = [
            OrderListItem(
                id=order.id,
                state=order.state,
                amount=order.amount,
                currency=order.currency,
                created_at=order.created_at,
                updated_at=order.updated_at,
                item_count=count,
            )
            for order, count in rows
        ]
        return OrderListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )
