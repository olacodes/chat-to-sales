"""
app/modules/orders/service.py

OrderService — orchestrates the order lifecycle.

WhatsApp-driven entry points (Feature 2):
  handle_inbound_customer_message() — parses customer orders and manages the
      customer confirmation flow via Redis session.
  handle_trader_command() — interprets CONFIRM/CANCEL/PAID/DELIVERED commands
      from the trader and transitions the order state machine accordingly.

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
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.infra.database import async_session_factory
from app.infra.event_bus import Event, publish_event
from app.modules.notifications.service import NotificationService
from app.modules.orders.models import Order, OrderState
from app.modules.orders.nlp import (
    CANCEL,
    CONFIRM,
    ORDER,
    TRADER_ADD,
    TRADER_CANCEL,
    TRADER_CATALOGUE,
    TRADER_CATEGORY,
    TRADER_CONFIRM,
    TRADER_CREDIT,
    TRADER_DEBT,
    TRADER_ORDERS,
    TRADER_DELIVERED,
    TRADER_MENU,
    TRADER_PAID,
    TRADER_PAID_DEBT,
    TRADER_PRICE,
    TRADER_PRICELIST,
    TRADER_REMOVE,
    TRADER_WHO_OWES_ME,
    UNKNOWN,
    parse_message,
)
from app.modules.onboarding.repository import TraderRepository
from app.modules.orders.repository import OrderRepository
from app.modules.orders.schemas import OrderCreate, OrderItemCreate, OrderListResponse
from app.modules.orders.session import (
    AWAITING_CLARIFICATION,
    AWAITING_CUSTOMER_CONFIRMATION,
    clear_order_session,
    get_order_session,
    set_order_session,
)
from app.modules.orders.state_machine import InvalidTransitionError, validate_transition
import app.modules.orders.whatsapp as wa

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

        If an open inquiry order already exists for the conversation it is
        upserted: existing items are replaced with the new ones and the total
        is recomputed.  This handles the common case where an auto-created
        inquiry order exists before the agent fills in the details.
        """
        total = (
            sum(item.unit_price * item.quantity for item in data.items)
            if data.items
            else Decimal("0")
        )

        existing = await self._repo.get_open_order_for_conversation(
            conversation_id=data.conversation_id,
            tenant_id=data.tenant_id,
        )

        if existing is not None:
            # Upsert: replace items and update total/currency
            await self._repo.delete_items_for_order(order_id=existing.id)
            existing.amount = total or None
            existing.currency = data.currency
            self._db.add(existing)
            await self._db.flush()
            for item_data in data.items:
                await self._repo.add_item(
                    order_id=existing.id,
                    product_name=item_data.name,
                    quantity=item_data.quantity,
                    unit_price=item_data.unit_price,
                )
            await self._db.commit()
            return await self._reload(existing.id)

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

    async def handle_credit_sale_resolved(
        self, *, order_id: str, tenant_id: str
    ) -> Order | None:
        """
        Transition an order to COMPLETED when its linked credit sale is settled
        or written off.

        Accepts orders in CONFIRMED or PAID state (CONFIRMED → COMPLETED is
        allowed for credit sales that bypass the normal payment step).
        Returns None if the order is not found, already terminal, or the
        transition is not applicable.
        """
        order = await self._repo.get_by_id(order_id=order_id, tenant_id=tenant_id)
        if order is None:
            logger.warning(
                "handle_credit_sale_resolved: order not found order_id=%s", order_id
            )
            return None

        if order.state in (OrderState.COMPLETED, OrderState.FAILED):
            logger.info(
                "handle_credit_sale_resolved: order already terminal order_id=%s state=%s",
                order_id,
                order.state,
            )
            return order

        try:
            order = await self._transition(order, OrderState.COMPLETED)
        except ConflictError as exc:
            logger.warning(
                "handle_credit_sale_resolved: cannot transition order_id=%s state=%s: %s",
                order_id,
                order.state,
                exc,
            )
            return None

        return order

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

    # ── WhatsApp-driven order flow ────────────────────────────────────────────

    async def handle_inbound_customer_message(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        customer_phone: str,
        message: str,
        message_id: str,
        trader: dict[str, Any],
        channel_tenant_id: str | None = None,
    ) -> None:
        """
        Process an inbound customer message and advance the order conversation.

        State machine (stored in Redis, keyed by tenant+customer_phone):

          [no session]
              Order intent detected
                  -> show summary to customer, notify trader, create INQUIRY order
                  -> set session: AWAITING_CUSTOMER_CONFIRMATION
              Clarification needed
                  -> ask one specific question
                  -> set session: AWAITING_CLARIFICATION
              Unknown / greeting
                  -> prompt for what they want to order

          AWAITING_CUSTOMER_CONFIRMATION
              YES -> transition order to CONFIRMED (trader already notified)
              NO  -> transition order to FAILED, clear session

          AWAITING_CLARIFICATION
              Re-parse with Claude including prior context
              -> update session items or show summary

        trader dict keys: business_name, business_category, catalogue (dict[str,int])
        channel_tenant_id: if set, outbound WhatsApp messages use this tenant's
            channel credentials (platform-routing scenario).
        """
        trader_name: str = trader.get("business_name", "the trader")
        category: str = trader.get("business_category", "")
        catalogue: dict[str, int] = trader.get("catalogue", {})

        session = await get_order_session(tenant_id, customer_phone)

        # ── Existing session: customer is responding to a summary ─────────────
        if session and session.get("state") == AWAITING_CUSTOMER_CONFIRMATION:
            # Handle quantity selection — from list tap (QTY_1) or typed (I want 7)
            import re as _re
            qty: int | None = None
            qty_match = message.strip().upper()

            if qty_match.startswith("QTY_"):
                # Interactive list tap: QTY_1, QTY_2, etc.
                try:
                    qty = int(qty_match.split("_")[1])
                except (IndexError, ValueError):
                    qty = 1
            else:
                # Typed message: extract quantity from digits or number words.
                # Supports: "7", "I want 7", "give me three", "meji" (Yoruba)
                from app.modules.orders.nlp import _WORD_TO_NUM

                # First try digit match
                num_match = _re.search(r"\b(\d+)\b", message.strip())
                if num_match:
                    parsed = int(num_match.group(1))
                    if 1 <= parsed <= 1000:
                        qty = parsed
                else:
                    # Try word-to-number (English + Yoruba)
                    for word in message.strip().lower().split():
                        if word in _WORD_TO_NUM:
                            qty = _WORD_TO_NUM[word]
                            break

            if qty is not None:
                if qty < 1:
                    qty = 1
                # Update order items with the selected quantity
                order_id = session["order_id"]
                order = await self._repo.get_by_id(order_id=order_id, tenant_id=tenant_id)
                if order and order.state == OrderState.INQUIRY and order.items:
                    item = order.items[0]
                    item.quantity = qty
                    order.amount = Decimal(str(int(item.unit_price) * qty))
                    self._db.add(order)
                    await self._db.flush()
                    # Update session with new total
                    session_items = session.get("items", [])
                    if session_items:
                        session_items[0]["qty"] = qty
                    session["total"] = int(order.amount)
                # Treat as a confirmation — fall through to CONFIRM logic below
                message = "YES"

            result = await parse_message(message, category=category, catalogue=catalogue)

            if result.intent == CONFIRM:
                order_id: str = session["order_id"]
                order = await self._repo.get_by_id(order_id=order_id, tenant_id=tenant_id)
                if order is None or order.state != OrderState.INQUIRY:
                    await clear_order_session(tenant_id, customer_phone)
                    await self._reply(
                        phone=customer_phone,
                        tenant_id=tenant_id,
                        event_id=f"order.customer_confirm_missing.{message_id}",
                        text="Something went wrong with your order. Abeg place it again.",
                        channel_tenant_id=channel_tenant_id,
                    )
                    return

                # Notify trader of the confirmed customer intent
                items: list[dict[str, Any]] = session.get("items", [])
                total: int = session.get("total", 0)
                order_ref = order.id[:8]
                trader_phone_number: str = trader.get("phone_number", "")

                # If the order came from an image inquiry, send the customer's
                # photo first, then the interactive buttons as a reply to it.
                photo_wamid: str | None = None
                session_media_id: str | None = session.get("media_id")
                if session_media_id and trader_phone_number:
                    photo_wamid = await self._reply_image(
                        phone=trader_phone_number,
                        tenant_id=tenant_id,
                        event_id=f"order.image_notify_trader.{order.id}",
                        media_id=session_media_id,
                        caption=f"Customer +{customer_phone} wants to buy this item:",
                        channel_tenant_id=channel_tenant_id,
                    )

                body_text, buttons = wa.order_received_interactive(
                    items=items,
                    total=total,
                    customer_phone=customer_phone,
                    order_ref=order_ref,
                )
                await self._reply_interactive(
                    phone=trader_phone_number,
                    tenant_id=tenant_id,
                    event_id=f"order.trader_notify.{order.id}",
                    body_text=body_text,
                    buttons=buttons,
                    channel_tenant_id=channel_tenant_id,
                    context_message_id=photo_wamid,
                )
                await clear_order_session(tenant_id, customer_phone)
                await self._reply(
                    phone=customer_phone,
                    tenant_id=tenant_id,
                    event_id=f"order.customer_pending.{order.id}",
                    text=wa.order_pending_to_customer(trader_name),
                    channel_tenant_id=channel_tenant_id,
                )
                logger.info(
                    "Customer confirmed order order_id=%s customer=%s",
                    order.id,
                    customer_phone,
                )
                return

            if result.intent == CANCEL:
                order_id = session.get("order_id", "")
                if order_id:
                    order = await self._repo.get_by_id(order_id=order_id, tenant_id=tenant_id)
                    if order and order.state == OrderState.INQUIRY:
                        try:
                            await self._transition(order, OrderState.FAILED)
                            await self._db.commit()
                        except ConflictError:
                            pass
                await clear_order_session(tenant_id, customer_phone)
                await self._reply(
                    phone=customer_phone,
                    tenant_id=tenant_id,
                    event_id=f"order.customer_cancel.{message_id}",
                    text=wa.order_cancelled_to_customer(trader_name),
                    channel_tenant_id=channel_tenant_id,
                )
                logger.info("Customer cancelled order customer=%s", customer_phone)
                return

            # Customer sent something else — re-show the summary
            items = session.get("items", [])
            total = session.get("total", 0)
            await self._reply(
                phone=customer_phone,
                tenant_id=tenant_id,
                event_id=f"order.re_summary.{message_id}",
                text=wa.order_summary_to_customer(items, total, trader_name),
                channel_tenant_id=channel_tenant_id,
            )
            return

        # ── Existing session: waiting for clarification answer ────────────────
        if session and session.get("state") == AWAITING_CLARIFICATION:
            # Append the clarification answer to the original message and re-parse
            original = session.get("original_message", "")
            combined = f"{original}. {message}"
            result = await parse_message(combined, category=category, catalogue=catalogue)
            # Fall through to handle result as a fresh order below
        else:
            result = await parse_message(message, category=category, catalogue=catalogue)

        # ── No session (or just resolved clarification): fresh order parse ────

        if result.intent == CONFIRM and not session:
            await self._reply(
                phone=customer_phone,
                tenant_id=tenant_id,
                event_id=f"order.stale_confirm.{message_id}",
                text=wa.no_active_session(),
                channel_tenant_id=channel_tenant_id,
            )
            return

        if result.intent == CANCEL and not session:
            await self._reply(
                phone=customer_phone,
                tenant_id=tenant_id,
                event_id=f"order.stale_cancel.{message_id}",
                text=wa.no_active_session(),
                channel_tenant_id=channel_tenant_id,
            )
            return

        if result.intent == UNKNOWN or (result.intent == ORDER and not result.items):
            if result.clarification_needed and result.clarification_question:
                # Save context and ask the clarification question
                await set_order_session(
                    tenant_id,
                    customer_phone,
                    {
                        "state": AWAITING_CLARIFICATION,
                        "original_message": message,
                    },
                )
                await self._reply(
                    phone=customer_phone,
                    tenant_id=tenant_id,
                    event_id=f"order.clarify.{message_id}",
                    text=wa.ask_clarification(result.clarification_question),
                    channel_tenant_id=channel_tenant_id,
                )
            else:
                await self._reply(
                    phone=customer_phone,
                    tenant_id=tenant_id,
                    event_id=f"order.unknown.{message_id}",
                    text=wa.unknown_order_prompt(),
                    channel_tenant_id=channel_tenant_id,
                )
            return

        # ── We have an ORDER with items ────────────────────────────────────────
        items = result.items
        # Fill in prices from catalogue for items that don't have them
        missing_price_names: list[str] = []
        for item in items:
            if item.get("unit_price") is None:
                # Case-insensitive catalogue lookup
                matched_price: int | None = None
                item_name_lower = item["name"].lower()
                for cat_name, cat_price in catalogue.items():
                    if item_name_lower in cat_name.lower() or cat_name.lower() in item_name_lower:
                        matched_price = cat_price
                        break
                if matched_price is not None:
                    item["unit_price"] = matched_price
                else:
                    missing_price_names.append(item["name"])

        if missing_price_names:
            await self._reply(
                phone=customer_phone,
                tenant_id=tenant_id,
                event_id=f"order.price_missing.{message_id}",
                text=wa.price_missing_prompt(missing_price_names),
                channel_tenant_id=channel_tenant_id,
            )
            return

        # All prices known — compute total and create the order in DB
        total = sum(item["qty"] * item["unit_price"] for item in items)

        order = await self._repo.create_order(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            customer_phone=customer_phone,
            trader_phone=trader.get("phone_number"),
            amount=Decimal(str(total)),
        )
        for item in items:
            await self._repo.add_item(
                order_id=order.id,
                product_name=item["name"],
                quantity=item["qty"],
                unit_price=Decimal(str(item["unit_price"])),
            )
        await self._db.commit()

        order_ref = order.id[:8]

        # Show summary to customer, store session awaiting their YES/NO
        await set_order_session(
            tenant_id,
            customer_phone,
            {
                "state": AWAITING_CUSTOMER_CONFIRMATION,
                "order_id": order.id,
                "items": items,
                "total": total,
            },
        )
        body_text, buttons = wa.order_summary_interactive(items, total, trader_name)
        await self._reply_interactive(
            phone=customer_phone,
            tenant_id=tenant_id,
            event_id=f"order.summary.{order.id}",
            body_text=body_text,
            buttons=buttons,
            channel_tenant_id=channel_tenant_id,
        )
        logger.info(
            "Order summary shown to customer order_id=%s customer=%s total=%s",
            order.id,
            customer_phone,
            total,
        )

    async def handle_image_inquiry(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        customer_phone: str,
        message: str,
        message_id: str,
        image_bytes: bytes,
        media_id: str,
        trader: dict[str, Any],
        channel_tenant_id: str | None = None,
    ) -> None:
        """
        Process a customer product inquiry via image.

        1. Compute pHash and check against stored image hashes (fastest, no API).
        2. If no hash match, try Claude Vision against the catalogue (only if
           catalogue has items).
        3. If no match — forward the image to the trader for manual pricing and
           store a pending inquiry session so the trader's reply can be learned.
        """
        from app.modules.onboarding.media import compute_phash, describe_product_image
        from app.modules.orders.product_descriptions import ProductDescriptionRepository
        from app.modules.orders.session import set_pending_image_inquiry

        trader_name: str = trader.get("business_name", "the trader")
        catalogue: dict[str, int] = trader.get("catalogue", {})
        category: str = trader.get("business_category", "")
        trader_phone: str = trader.get("phone_number", "")

        # Compute perceptual hash for image matching (fast, no API call)
        image_hash: str | None = None
        try:
            image_hash = compute_phash(image_bytes)
        except Exception as exc:
            logger.warning("pHash computation failed sender=%s: %s", customer_phone, exc)

        # Check stored image hashes BEFORE Claude Vision (fastest path, no API cost)
        if image_hash and trader_phone:
            pd_repo = ProductDescriptionRepository(self._db)
            learned = await pd_repo.find_best_match(
                trader_phone=trader_phone,
                new_image_hash=image_hash,
                catalogue=catalogue,
            )
            if learned:
                logger.info(
                    "Image hash match: product=%s distance=%d customer=%s",
                    learned["product_name"],
                    learned["distance"],
                    customer_phone,
                )
                await self._create_image_order(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    customer_phone=customer_phone,
                    trader=trader,
                    product_name=learned["product_name"],
                    price=learned["price"],
                    trader_name=trader_name,
                    channel_tenant_id=channel_tenant_id,
                    media_id=media_id,
                )
                return

        # ── Try Claude Vision catalogue matching (only if catalogue has items) ──
        if catalogue:
            await self._reply(
                phone=customer_phone,
                tenant_id=tenant_id,
                event_id=f"order.image_ack.{message_id}",
                text="I see your photo! Let me check... \U0001f50d",
                channel_tenant_id=channel_tenant_id,
            )

            try:
                analysis = await describe_product_image(
                    image_bytes=image_bytes,
                    catalogue=catalogue,
                    category=category,
                )
                matched_product: str | None = analysis.get("matched_product")
                matched_price: int | None = analysis.get("matched_price")
                confidence: float = analysis.get("confidence", 0.0)

                if matched_product and matched_price and confidence >= 0.7:
                    await self._create_image_order(
                        tenant_id=tenant_id,
                        conversation_id=conversation_id,
                        customer_phone=customer_phone,
                        trader=trader,
                        product_name=matched_product,
                        price=matched_price,
                        trader_name=trader_name,
                        channel_tenant_id=channel_tenant_id,
                        media_id=media_id,
                    )
                    return
            except Exception as exc:
                logger.warning("Claude Vision failed sender=%s: %s", customer_phone, exc)

        # ── Not matched: forward image to trader ──────────────────────────────
        await self._reply(
            phone=customer_phone,
            tenant_id=tenant_id,
            event_id=f"order.image_forwarded.{message_id}",
            text=wa.image_inquiry_forwarded(trader_name),
            channel_tenant_id=channel_tenant_id,
        )

        if trader_phone:
            caption = wa.image_inquiry_to_trader(customer_phone)
            await self._reply_image(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"order.image_to_trader.{message_id}",
                media_id=media_id,
                caption=caption,
                channel_tenant_id=channel_tenant_id,
            )

            # Store pending inquiry so trader's price reply can be learned
            await set_pending_image_inquiry(
                trader_phone,
                {
                    "customer_phone": customer_phone,
                    "image_hash": image_hash or "",
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                    "channel_tenant_id": channel_tenant_id or "",
                },
            )

        logger.info(
            "Image inquiry forwarded to trader=%s customer=%s",
            trader_phone,
            customer_phone,
        )

    async def _handle_image_inquiry_reply(
        self,
        *,
        trader_phone: str,
        message: str,
        message_id: str,
        trader: dict[str, Any],
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> bool:
        """
        Check if the trader is replying to a pending image inquiry with a price.

        Expected reply formats:
            "8500"               — price only (product saved as "Product")
            "Indomie Carton 8500" — product name + price

        If a pending inquiry exists and the reply contains a price:
        1. Save the image hash + product name as a confirmed ProductDescription
        2. Notify the customer with the price
        3. Create an order in INQUIRY state for the customer
        4. Clear the pending inquiry session

        Returns True if handled, False if no pending inquiry or invalid reply.
        """
        import re
        from app.modules.orders.product_descriptions import ProductDescriptionRepository
        from app.modules.orders.session import (
            get_pending_image_inquiry,
            clear_pending_image_inquiry,
            count_pending_image_inquiries,
        )

        pending = await get_pending_image_inquiry(trader_phone)
        if pending is None:
            return False

        # Parse the trader's reply: extract a price (last number in the message)
        text = message.strip()
        # Remove commas from numbers (e.g. "8,500" → "8500")
        cleaned = re.sub(r"(\d),(\d)", r"\1\2", text)
        # Find all numbers
        numbers = re.findall(r"\d+", cleaned)
        if not numbers:
            return False  # No price found — not a reply to the image inquiry

        price = int(numbers[-1])  # last number is the price
        if price <= 0:
            return False

        # Extract product name: everything before the price, or use description
        price_str = numbers[-1]
        idx = cleaned.rfind(price_str)
        name_part = cleaned[:idx].strip().rstrip("-–—:").strip()

        catalogue: dict[str, int] = trader.get("catalogue", {})
        pending_image_hash: str = pending.get("image_hash", "")
        customer_phone: str = pending["customer_phone"]
        pending_tenant_id: str = pending["tenant_id"]
        conversation_id: str = pending.get("conversation_id", "")
        pending_channel_tenant_id: str = pending.get("channel_tenant_id") or None

        # Determine product name: trader-specified > fuzzy catalogue match > generic
        product_name = ""
        if name_part:
            # Trader typed a name — use it, but check catalogue for exact match
            name_lower = name_part.lower()
            for cat_name in catalogue:
                if name_lower in cat_name.lower() or cat_name.lower() in name_lower:
                    product_name = cat_name
                    break
            if not product_name:
                product_name = name_part
        else:
            # Price only — use generic name (trader can update later)
            product_name = "Product"

        trader_name: str = trader.get("business_name", "the trader")

        # Save the learned product with image hash and price
        pd_repo = ProductDescriptionRepository(self._db)
        await pd_repo.save(
            trader_phone=trader_phone,
            product_name=product_name,
            price=price,
            image_hash=pending_image_hash or None,
            confirmed=True,
        )

        # Update the trader's catalogue with the new product/price
        catalogue[product_name] = price

        # Notify the trader
        await self._reply(
            phone=trader_phone,
            tenant_id=tenant_id,
            event_id=f"order.image_learned.{message_id}",
            text=wa.image_inquiry_price_saved(product_name, price),
            channel_tenant_id=channel_tenant_id,
        )

        # Create order and notify customer
        if customer_phone and conversation_id:
            await self._create_image_order(
                tenant_id=pending_tenant_id,
                conversation_id=conversation_id,
                customer_phone=customer_phone,
                trader=trader,
                product_name=product_name,
                price=price,
                trader_name=trader_name,
                channel_tenant_id=pending_channel_tenant_id,
            )

        await self._db.commit()
        await clear_pending_image_inquiry(trader_phone, customer_phone=customer_phone)

        # Notify trader if more inquiries are waiting
        remaining = await count_pending_image_inquiries(trader_phone)
        if remaining > 0:
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"order.image_more_pending.{message_id}",
                text=wa.image_inquiry_more_pending(remaining),
                channel_tenant_id=channel_tenant_id,
            )

        logger.info(
            "Image inquiry learned: trader=%s product=%s price=%d customer=%s remaining=%d",
            trader_phone,
            product_name,
            price,
            customer_phone,
            remaining,
        )
        return True

    # ── Catalogue management helpers ─────────────────────────────────────────

    async def _send_trader_menu(
        self,
        *,
        trader_phone: str,
        message_id: str,
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        body, button_label, sections = wa.trader_menu()
        await self._reply_list(
            phone=trader_phone,
            tenant_id=tenant_id,
            event_id=f"trader.menu.{message_id}",
            body_text=body,
            button_label=button_label,
            sections=sections,
            channel_tenant_id=channel_tenant_id,
        )

    async def _handle_menu_tap(
        self,
        *,
        tap: str,
        trader_phone: str,
        message_id: str,
        trader: dict[str, Any],
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        from app.modules.orders.session import set_trader_session, TRADER_AWAITING_ADD

        trader_name = trader.get("business_name", "the trader")
        catalogue: dict[str, int] = trader.get("catalogue", {})
        store_slug: str = trader.get("store_slug", "")

        if tap == "MENU_CATALOGUE":
            if not catalogue:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.catalogue.{message_id}",
                    text=wa.catalogue_list(catalogue, trader_name),
                    channel_tenant_id=channel_tenant_id,
                )
            else:
                body, btn, sections = wa.catalogue_picker(catalogue, trader_name)
                await self._reply_list(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.catalogue.{message_id}",
                    body_text=body,
                    button_label=btn,
                    sections=sections,
                    channel_tenant_id=channel_tenant_id,
                )
        elif tap == "MENU_ADD":
            await set_trader_session(trader_phone, {"state": TRADER_AWAITING_ADD})
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.add_prompt.{message_id}",
                text=wa.add_product_prompt(),
                channel_tenant_id=channel_tenant_id,
            )
        elif tap == "MENU_REMOVE":
            if not catalogue:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.remove_empty.{message_id}",
                    text="Your catalogue is empty — nothing to remove.",
                    channel_tenant_id=channel_tenant_id,
                )
            else:
                body, btn, sections = wa.remove_product_list(catalogue)
                await self._reply_list(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.remove_picker.{message_id}",
                    body_text=body,
                    button_label=btn,
                    sections=sections,
                    channel_tenant_id=channel_tenant_id,
                )
        elif tap == "MENU_PRICE":
            if not catalogue:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.price_empty.{message_id}",
                    text="Your catalogue is empty — add products first.",
                    channel_tenant_id=channel_tenant_id,
                )
            else:
                body, btn, sections = wa.price_product_list(catalogue)
                await self._reply_list(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.price_picker.{message_id}",
                    body_text=body,
                    button_label=btn,
                    sections=sections,
                    channel_tenant_id=channel_tenant_id,
                )
        elif tap == "MENU_STORE":
            product_count = len(catalogue)
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.store_info.{message_id}",
                text=wa.store_info(store_slug, trader_name, product_count),
                channel_tenant_id=channel_tenant_id,
            )
        elif tap == "MENU_PRICELIST":
            from app.modules.orders.session import set_trader_session, TRADER_AWAITING_PRICELIST_PHOTO
            await set_trader_session(trader_phone, {
                "state": TRADER_AWAITING_PRICELIST_PHOTO,
                "ocr_texts": [],
                "photo_count": 0,
            })
            body, buttons = wa.pricelist_prompt()
            await self._reply_interactive(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.pricelist_prompt.{message_id}",
                body_text=body,
                buttons=buttons,
                channel_tenant_id=channel_tenant_id,
            )
        elif tap == "MENU_CATEGORY":
            current_cat = trader.get("business_category", "")
            body, btn, sections = wa.category_picker(current_cat)
            await self._reply_list(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.category_picker.{message_id}",
                body_text=body,
                button_label=btn,
                sections=sections,
                channel_tenant_id=channel_tenant_id,
            )
        elif tap == "MENU_ORDERS":
            await self._do_list_pending_orders(
                trader_phone=trader_phone,
                message_id=message_id,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
        elif tap == "MENU_HELP":
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.help.{message_id}",
                text=wa.trader_command_guide(),
                channel_tenant_id=channel_tenant_id,
            )

    async def _handle_trader_session(
        self,
        *,
        tsession: dict[str, Any],
        trader_phone: str,
        message: str,
        message_id: str,
        trader: dict[str, Any],
        tenant_id: str,
        channel_tenant_id: str | None = None,
        image_bytes: bytes | None = None,
    ) -> bool:
        """Handle multi-step catalogue flows. Returns True if handled."""
        import re as _re
        from app.modules.orders.session import (
            clear_trader_session,
            set_trader_session,
            TRADER_AWAITING_ADD,
            TRADER_AWAITING_PRICE_VALUE,
            TRADER_AWAITING_PRICELIST_PHOTO,
            TRADER_AWAITING_PRICELIST_CONFIRM,
        )

        state = tsession.get("state", "")

        if state == TRADER_AWAITING_PRICELIST_PHOTO:
            _MAX_PRICELIST_PHOTOS = 10
            ocr_texts: list[str] = tsession.get("ocr_texts", [])
            photo_count: int = tsession.get("photo_count", 0)
            category: str = trader.get("business_category", "")

            # "Done" button tap or typed "done" — process all collected texts
            answer = message.strip().upper()
            if answer in ("DONE", "PRICELIST_DONE"):
                if not ocr_texts:
                    # No photos sent yet — re-prompt
                    body, buttons = wa.pricelist_prompt()
                    await self._reply_interactive(
                        phone=trader_phone,
                        tenant_id=tenant_id,
                        event_id=f"trader.pricelist_reprompt.{message_id}",
                        body_text=body,
                        buttons=buttons,
                        channel_tenant_id=channel_tenant_id,
                    )
                    return True
                await self._process_pricelist_texts(
                    ocr_texts=ocr_texts,
                    category=category,
                    trader_phone=trader_phone,
                    message_id=message_id,
                    trader=trader,
                    tenant_id=tenant_id,
                    channel_tenant_id=channel_tenant_id,
                )
                return True

            # Photo received — OCR immediately, collect text
            if image_bytes:
                try:
                    from app.modules.onboarding.media import ocr_image_bytes
                    ocr_text = await ocr_image_bytes(image_bytes)
                except Exception as exc:
                    logger.warning("Pricelist OCR failed: %s", exc)
                    ocr_text = ""
                if not ocr_text:
                    # OCR failed — tell the trader, don't count it
                    await self._reply(
                        phone=trader_phone,
                        tenant_id=tenant_id,
                        event_id=f"trader.pricelist_ocr_fail.{message_id}",
                        text="I no fit read that photo. \U0001f914 Try a clearer one or send another.",
                        channel_tenant_id=channel_tenant_id,
                    )
                    return True
                ocr_texts.append(ocr_text)
                photo_count += 1

                # Auto-trigger processing at max photos
                if photo_count >= _MAX_PRICELIST_PHOTOS:
                    await self._reply(
                        phone=trader_phone,
                        tenant_id=tenant_id,
                        event_id=f"trader.pricelist_maxphotos.{message_id}",
                        text=f"\U0001f4f8 {photo_count} photos received (maximum). Processing now...",
                        channel_tenant_id=channel_tenant_id,
                    )
                    await self._process_pricelist_texts(
                        ocr_texts=ocr_texts,
                        category=category,
                        trader_phone=trader_phone,
                        message_id=message_id,
                        trader=trader,
                        tenant_id=tenant_id,
                        channel_tenant_id=channel_tenant_id,
                    )
                    return True

                # Save updated session and acknowledge
                await set_trader_session(trader_phone, {
                    "state": TRADER_AWAITING_PRICELIST_PHOTO,
                    "ocr_texts": ocr_texts,
                    "photo_count": photo_count,
                })
                body, buttons = wa.pricelist_photo_received(photo_count)
                await self._reply_interactive(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.pricelist_photo_{photo_count}.{message_id}",
                    body_text=body,
                    buttons=buttons,
                    channel_tenant_id=channel_tenant_id,
                )
                return True

            # Voice note transcription or typed text — collect as OCR text
            if message and message != "[image]":
                ocr_texts.append(message)
                photo_count += 1
                await set_trader_session(trader_phone, {
                    "state": TRADER_AWAITING_PRICELIST_PHOTO,
                    "ocr_texts": ocr_texts,
                    "photo_count": photo_count,
                })
                body, buttons = wa.pricelist_photo_received(photo_count)
                await self._reply_interactive(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.pricelist_voice_{photo_count}.{message_id}",
                    body_text=body,
                    buttons=buttons,
                    channel_tenant_id=channel_tenant_id,
                )
                return True

            # No image/text — re-prompt
            body, buttons = wa.pricelist_prompt()
            await self._reply_interactive(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.pricelist_reprompt.{message_id}",
                body_text=body,
                buttons=buttons,
                channel_tenant_id=channel_tenant_id,
            )
            return True

        if state == TRADER_AWAITING_PRICELIST_CONFIRM:
            await clear_trader_session(trader_phone)
            answer = message.strip().upper()
            if answer in ("YES", "PRICELIST_YES"):
                items = tsession.get("items", [])
                catalogue: dict[str, int] = dict(trader.get("catalogue", {}))
                for item in items:
                    name = item["name"]
                    price = item["price"]
                    # Case-insensitive merge: update existing key or add new
                    matched_key: str | None = None
                    for key in catalogue:
                        if key.lower() == name.lower():
                            matched_key = key
                            break
                    if matched_key:
                        catalogue[matched_key] = price
                    else:
                        catalogue[name] = price
                await self._persist_catalogue(trader_phone, catalogue)
                new_count = tsession.get("new_count", 0)
                updated_count = tsession.get("updated_count", 0)
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.pricelist_confirmed.{message_id}",
                    text=wa.pricelist_confirmed(new_count, updated_count, len(catalogue)),
                    channel_tenant_id=channel_tenant_id,
                )
            else:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.pricelist_cancelled.{message_id}",
                    text=wa.pricelist_cancelled(),
                    channel_tenant_id=channel_tenant_id,
                )
            return True

        if state == TRADER_AWAITING_ADD:
            await clear_trader_session(trader_phone)
            # Parse single or batch: "Milo 3500" or "Milo 3500, Garri 2500"
            from app.modules.orders.nlp import _parse_add_items
            # Prepend "ADD " so the parser can handle it uniformly
            items = _parse_add_items(f"ADD {message}")
            if items:
                await self._do_add_products(
                    trader_phone=trader_phone,
                    items=items,
                    message_id=message_id,
                    trader=trader,
                    tenant_id=tenant_id,
                    channel_tenant_id=channel_tenant_id,
                )
                return True
            # Could not parse — prompt again
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.add_invalid.{message_id}",
                text=(
                    "I no understand that. Type product name and price like:\n\n"
                    "_Milo 3500_\n\n"
                    "Or add many at once:\n"
                    "_Milo 3500, Garri 2500, Rice 63000_"
                ),
                channel_tenant_id=channel_tenant_id,
            )
            return True

        if state == TRADER_AWAITING_PRICE_VALUE:
            await clear_trader_session(trader_phone)
            product_name = tsession.get("product_name", "")
            cleaned = _re.sub(r"(\d),(\d)", r"\1\2", message.strip())
            numbers = _re.findall(r"\d+", cleaned)
            if numbers:
                new_price = int(numbers[0])
                if new_price > 0 and product_name:
                    await self._do_update_price(
                        trader_phone=trader_phone,
                        product_name=product_name,
                        new_price=new_price,
                        message_id=message_id,
                        trader=trader,
                        tenant_id=tenant_id,
                        channel_tenant_id=channel_tenant_id,
                    )
                    return True
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.price_invalid.{message_id}",
                text="I no understand that. Just type the new price like:\n\n_9000_",
                channel_tenant_id=channel_tenant_id,
            )
            return True

        return False

    async def _do_add_products(
        self,
        *,
        trader_phone: str,
        items: list[dict[str, Any]],
        message_id: str,
        trader: dict[str, Any],
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        """Add one or more products to the catalogue in a single persist + reply."""
        catalogue: dict[str, int] = dict(trader.get("catalogue", {}))
        added: list[tuple[str, int]] = []
        for item in items:
            name = item["name"]
            price = item["unit_price"]
            catalogue[name] = price
            added.append((name, price))
        await self._persist_catalogue(trader_phone, catalogue)
        if len(added) == 1:
            text = wa.product_added(added[0][0], added[0][1])
        else:
            text = wa.products_added_batch(added)
        await self._reply(
            phone=trader_phone,
            tenant_id=tenant_id,
            event_id=f"trader.added.{message_id}",
            text=text,
            channel_tenant_id=channel_tenant_id,
        )

    async def _do_remove_product(
        self,
        *,
        trader_phone: str,
        product_name: str,
        message_id: str,
        trader: dict[str, Any],
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        catalogue: dict[str, int] = dict(trader.get("catalogue", {}))
        # Case-insensitive removal
        matched_key: str | None = None
        for key in catalogue:
            if key.lower() == product_name.lower():
                matched_key = key
                break
        if matched_key is None:
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.remove_notfound.{message_id}",
                text=wa.product_not_found(product_name),
                channel_tenant_id=channel_tenant_id,
            )
            return
        del catalogue[matched_key]
        await self._persist_catalogue(trader_phone, catalogue)
        await self._reply(
            phone=trader_phone,
            tenant_id=tenant_id,
            event_id=f"trader.removed.{message_id}",
            text=wa.product_removed(matched_key),
            channel_tenant_id=channel_tenant_id,
        )

    async def _do_remove_products(
        self,
        *,
        trader_phone: str,
        names: list[str],
        message_id: str,
        trader: dict[str, Any],
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        """Remove one or more products from the catalogue in a single persist + reply."""
        catalogue: dict[str, int] = dict(trader.get("catalogue", {}))
        removed: list[str] = []
        not_found: list[str] = []
        for name in names:
            matched_key: str | None = None
            for key in catalogue:
                if key.lower() == name.lower():
                    matched_key = key
                    break
            if matched_key:
                del catalogue[matched_key]
                removed.append(matched_key)
            else:
                not_found.append(name)
        if removed:
            await self._persist_catalogue(trader_phone, catalogue)
            if len(removed) == 1:
                text = wa.product_removed(removed[0])
            else:
                text = wa.products_removed_batch(removed)
            if not_found:
                text += f"\n\nI no fit find: {', '.join(not_found)}"
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.removed.{message_id}",
                text=text,
                channel_tenant_id=channel_tenant_id,
            )
        else:
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.remove_notfound.{message_id}",
                text=wa.product_not_found(", ".join(not_found)),
                channel_tenant_id=channel_tenant_id,
            )

    async def _do_update_price(
        self,
        *,
        trader_phone: str,
        product_name: str,
        new_price: int,
        message_id: str,
        trader: dict[str, Any],
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        catalogue: dict[str, int] = dict(trader.get("catalogue", {}))
        matched_key: str | None = None
        old_price: int = 0
        for key, val in catalogue.items():
            if key.lower() == product_name.lower():
                matched_key = key
                old_price = val
                break
        if matched_key is None:
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.price_notfound.{message_id}",
                text=wa.product_not_found(product_name),
                channel_tenant_id=channel_tenant_id,
            )
            return
        catalogue[matched_key] = new_price
        await self._persist_catalogue(trader_phone, catalogue)
        await self._reply(
            phone=trader_phone,
            tenant_id=tenant_id,
            event_id=f"trader.price_updated.{message_id}",
            text=wa.product_price_updated(matched_key, old_price, new_price),
            channel_tenant_id=channel_tenant_id,
        )

    async def _do_update_prices(
        self,
        *,
        trader_phone: str,
        items: list[dict[str, Any]],
        message_id: str,
        trader: dict[str, Any],
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        """Update one or more product prices in a single persist + reply."""
        catalogue: dict[str, int] = dict(trader.get("catalogue", {}))
        updated: list[tuple[str, int, int]] = []  # (name, old_price, new_price)
        not_found: list[str] = []
        for item in items:
            name = item["name"]
            new_price = item["unit_price"]
            matched_key: str | None = None
            old_price: int = 0
            for key, val in catalogue.items():
                if key.lower() == name.lower():
                    matched_key = key
                    old_price = val
                    break
            if matched_key:
                catalogue[matched_key] = new_price
                updated.append((matched_key, old_price, new_price))
            else:
                not_found.append(name)
        if updated:
            await self._persist_catalogue(trader_phone, catalogue)
            if len(updated) == 1:
                text = wa.product_price_updated(updated[0][0], updated[0][1], updated[0][2])
            else:
                text = wa.prices_updated_batch(updated)
            if not_found:
                text += f"\n\nI no fit find: {', '.join(not_found)}"
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.price_updated.{message_id}",
                text=text,
                channel_tenant_id=channel_tenant_id,
            )
        else:
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.price_notfound.{message_id}",
                text=wa.product_not_found(", ".join(not_found)),
                channel_tenant_id=channel_tenant_id,
            )

    # ── Debt tracker helpers ────────────────────────────────────────────────

    async def _do_create_debt(
        self,
        *,
        trader_phone: str,
        customer_name: str,
        amount: int,
        message_id: str,
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        """Create a credit sale (debt) from a WhatsApp DEBT command."""
        from decimal import Decimal as D
        from app.modules.credit_sales.models import CreditSale

        async with async_session_factory.begin() as session:
            credit_sale = CreditSale(
                tenant_id=tenant_id,
                customer_name=customer_name,
                amount=D(str(amount)),
                currency="NGN",
            )
            session.add(credit_sale)

        await self._reply(
            phone=trader_phone,
            tenant_id=tenant_id,
            event_id=f"trader.debt_created.{message_id}",
            text=wa.debt_created(customer_name, amount),
            channel_tenant_id=channel_tenant_id,
        )
        logger.info("Debt created: trader=%s customer=%s amount=%d", trader_phone, customer_name, amount)

    async def _do_settle_debt(
        self,
        *,
        trader_phone: str,
        customer_name: str,
        amount: int,
        message_id: str,
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        """Settle a debt by customer name (case-insensitive fuzzy match)."""
        from app.modules.credit_sales.models import CreditSale, CreditSaleStatus
        from sqlalchemy import select, func

        async with async_session_factory.begin() as session:
            # Find active debts for this customer name (case-insensitive)
            result = await session.execute(
                select(CreditSale).where(
                    CreditSale.tenant_id == tenant_id,
                    CreditSale.status == CreditSaleStatus.ACTIVE,
                    func.lower(CreditSale.customer_name) == customer_name.lower(),
                )
            )
            debts = list(result.scalars().all())

            if not debts:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.debt_notfound.{message_id}",
                    text=wa.debt_not_found(customer_name),
                    channel_tenant_id=channel_tenant_id,
                )
                return

            # Settle the first matching debt
            debt = debts[0]
            debt.status = CreditSaleStatus.SETTLED

        settled_amount = int(debt.amount)
        await self._reply(
            phone=trader_phone,
            tenant_id=tenant_id,
            event_id=f"trader.debt_settled.{message_id}",
            text=wa.debt_settled(debt.customer_name, settled_amount),
            channel_tenant_id=channel_tenant_id,
        )
        logger.info("Debt settled: trader=%s customer=%s amount=%d", trader_phone, customer_name, settled_amount)

    async def _do_list_debts(
        self,
        *,
        trader_phone: str,
        message_id: str,
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        """List all active debts for the trader."""
        from app.modules.credit_sales.models import CreditSale, CreditSaleStatus
        from sqlalchemy import select

        async with async_session_factory() as session:
            result = await session.execute(
                select(CreditSale).where(
                    CreditSale.tenant_id == tenant_id,
                    CreditSale.status == CreditSaleStatus.ACTIVE,
                ).order_by(CreditSale.created_at.desc())
            )
            debts = list(result.scalars().all())

        debt_list_data = [{"name": d.customer_name, "amount": int(d.amount)} for d in debts]
        total = sum(d["amount"] for d in debt_list_data)

        await self._reply(
            phone=trader_phone,
            tenant_id=tenant_id,
            event_id=f"trader.debt_list.{message_id}",
            text=wa.debt_list(debt_list_data, total),
            channel_tenant_id=channel_tenant_id,
        )

    async def _do_list_pending_orders(
        self,
        *,
        trader_phone: str,
        message_id: str,
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        """List all active (non-terminal) orders for the trader."""
        from sqlalchemy import select

        async with async_session_factory() as session:
            result = await session.execute(
                select(Order).where(
                    Order.trader_phone == trader_phone,
                    Order.state.in_([
                        OrderState.INQUIRY,
                        OrderState.CONFIRMED,
                        OrderState.PAID,
                    ]),
                ).order_by(Order.created_at.desc())
            )
            orders = list(result.scalars().all())

        if not orders:
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.orders_empty.{message_id}",
                text=wa.no_pending_orders(),
                channel_tenant_id=channel_tenant_id,
            )
            return

        order_data = []
        for o in orders:
            order_data.append({
                "ref": o.id[:8],
                "customer_phone": o.customer_phone or "",
                "amount": int(o.amount or 0),
                "date": o.created_at.strftime("%b %d") if o.created_at else "",
                "state": o.state,
                "is_credit": o.is_credit,
            })

        result_tuple = wa.pending_orders_list(order_data)
        if result_tuple is None:
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.orders_empty.{message_id}",
                text=wa.no_pending_orders(),
                channel_tenant_id=channel_tenant_id,
            )
            return

        body, btn, sections = result_tuple
        await self._reply_list(
            phone=trader_phone,
            tenant_id=tenant_id,
            event_id=f"trader.orders_list.{message_id}",
            body_text=body,
            button_label=btn,
            sections=sections,
            channel_tenant_id=channel_tenant_id,
        )

    async def _process_pricelist_texts(
        self,
        *,
        ocr_texts: list[str],
        category: str,
        trader_phone: str,
        message_id: str,
        trader: dict[str, Any],
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        """Combine collected OCR/voice texts, extract products, show confirmation."""
        from app.modules.orders.session import (
            clear_trader_session,
            set_trader_session,
            TRADER_AWAITING_PRICELIST_CONFIRM,
        )

        await self._reply(
            phone=trader_phone,
            tenant_id=tenant_id,
            event_id=f"trader.pricelist_processing.{message_id}",
            text=wa.pricelist_processing(),
            channel_tenant_id=channel_tenant_id,
        )

        combined_text = "\n\n".join(ocr_texts)
        try:
            from app.modules.onboarding.media import extract_products_from_text
            items = await extract_products_from_text(combined_text, category)
        except Exception as exc:
            logger.warning("Pricelist extract failed: %s", exc)
            items = []

        await clear_trader_session(trader_phone)

        if not items:
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.pricelist_empty.{message_id}",
                text=wa.pricelist_empty(),
                channel_tenant_id=channel_tenant_id,
            )
            return

        # Compute new vs updated counts
        catalogue = trader.get("catalogue", {})
        new_count = 0
        updated_count = 0
        for item in items:
            matched = False
            for key in catalogue:
                if key.lower() == item["name"].lower():
                    matched = True
                    break
            if matched:
                updated_count += 1
            else:
                new_count += 1

        await set_trader_session(trader_phone, {
            "state": TRADER_AWAITING_PRICELIST_CONFIRM,
            "items": items,
            "new_count": new_count,
            "updated_count": updated_count,
        })
        body_text, buttons = wa.pricelist_extracted(items, new_count, updated_count)
        await self._reply_interactive(
            phone=trader_phone,
            tenant_id=tenant_id,
            event_id=f"trader.pricelist_extracted.{message_id}",
            body_text=body_text,
            buttons=buttons,
            channel_tenant_id=channel_tenant_id,
        )

    async def _do_change_category(
        self,
        *,
        trader_phone: str,
        new_category: str,
        message_id: str,
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        """Update the trader's business category in DB and bust cache."""
        from app.modules.onboarding.catalogue_templates import CATEGORY_DISPLAY_NAMES
        from app.modules.orders.session import cache_trader_by_phone, get_trader_by_phone_cache

        display = CATEGORY_DISPLAY_NAMES.get(new_category, new_category)

        async with async_session_factory.begin() as session:
            repo = TraderRepository(session)
            await repo.update_category(
                phone_number=trader_phone, category=new_category
            )

        # Bust the trader cache so future messages use the new category
        cached = await get_trader_by_phone_cache(trader_phone)
        if cached and isinstance(cached, dict) and cached:
            cached["business_category"] = new_category
            await cache_trader_by_phone(trader_phone, cached)

        await self._reply(
            phone=trader_phone,
            tenant_id=tenant_id,
            event_id=f"trader.category_changed.{message_id}",
            text=wa.category_changed(display),
            channel_tenant_id=channel_tenant_id,
        )

    async def _persist_catalogue(
        self, trader_phone: str, catalogue: dict[str, int]
    ) -> None:
        """Save catalogue to DB and bust Redis trader cache."""
        from app.modules.orders.session import cache_trader_by_phone, get_trader_by_phone_cache

        async with async_session_factory.begin() as session:
            repo = TraderRepository(session)
            await repo.update_catalogue(
                phone_number=trader_phone, catalogue=catalogue
            )

        # Bust the trader cache so the order handler picks up the new catalogue
        cached = await get_trader_by_phone_cache(trader_phone)
        if cached and isinstance(cached, dict) and cached:
            cached["catalogue"] = catalogue
            await cache_trader_by_phone(trader_phone, cached)

    # ── Image order helpers ──────────────────────────────────────────────────

    async def _create_image_order(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        customer_phone: str,
        trader: dict[str, Any],
        product_name: str,
        price: int,
        trader_name: str,
        channel_tenant_id: str | None = None,
        media_id: str | None = None,
    ) -> None:
        """
        Create an INQUIRY order from an image match and ask the customer to
        select a quantity.  The trader is NOT notified here — notification
        happens after the customer confirms (in handle_inbound_customer_message).
        """
        items = [{"name": product_name, "qty": 1, "unit_price": price}]

        order = await self._repo.create_order(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            customer_phone=customer_phone,
            trader_phone=trader.get("phone_number"),
            amount=Decimal(str(price)),
        )
        await self._repo.add_item(
            order_id=order.id,
            product_name=product_name,
            quantity=1,
            unit_price=Decimal(str(price)),
        )
        await self._db.commit()

        # Store session with media_id so the CONFIRM handler can forward
        # the customer's photo to the trader alongside the order notification.
        session_data: dict[str, Any] = {
            "state": AWAITING_CUSTOMER_CONFIRMATION,
            "order_id": order.id,
            "items": items,
            "total": price,
        }
        if media_id:
            session_data["media_id"] = media_id
        await set_order_session(tenant_id, customer_phone, session_data)

        list_body, list_button, list_sections = wa.image_inquiry_matched_list(
            product_name, price, trader_name
        )
        await self._reply_list(
            phone=customer_phone,
            tenant_id=tenant_id,
            event_id=f"order.image_matched.{order.id}",
            body_text=list_body,
            button_label=list_button,
            sections=list_sections,
            channel_tenant_id=channel_tenant_id,
        )

        logger.info(
            "Image inquiry order created — awaiting customer qty selection "
            "product=%s price=%s order_id=%s customer=%s",
            product_name,
            price,
            order.id,
            customer_phone,
        )

    async def handle_cart_order(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        customer_phone: str,
        message_id: str,
        trader: dict[str, Any],
        cart_items: list[dict[str, Any]],
        channel_tenant_id: str | None = None,
    ) -> None:
        """
        Process a pre-structured order from the store cart.

        cart_items: list of {name: str, qty: int} — quantities already known,
        prices are resolved from the trader's catalogue.  If a price is missing
        for any item the customer is asked to provide it (falls back gracefully).

        This bypasses NLP parsing entirely; it is only called when the customer
        sent an ORDER:{slug} structured message generated by the StoreCatalogue UI.
        """
        trader_name: str = trader.get("business_name", "the trader")
        catalogue: dict[str, int] = trader.get("catalogue", {})

        items: list[dict[str, Any]] = []
        missing_price_names: list[str] = []

        for cart_item in cart_items:
            name: str = cart_item["name"]
            qty: int = cart_item["qty"]
            # Case-insensitive catalogue lookup
            matched_price: int | None = None
            name_lower = name.lower()
            for cat_name, cat_price in catalogue.items():
                if name_lower in cat_name.lower() or cat_name.lower() in name_lower:
                    matched_price = cat_price
                    break
            if matched_price is not None:
                items.append({"name": name, "qty": qty, "unit_price": matched_price})
            else:
                missing_price_names.append(name)

        if missing_price_names:
            await self._reply(
                phone=customer_phone,
                tenant_id=tenant_id,
                event_id=f"order.cart_price_missing.{message_id}",
                text=wa.price_missing_prompt(missing_price_names),
                channel_tenant_id=channel_tenant_id,
            )
            return

        total = sum(item["qty"] * item["unit_price"] for item in items)

        order = await self._repo.create_order(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            customer_phone=customer_phone,
            trader_phone=trader.get("phone_number"),
            amount=Decimal(str(total)),
        )
        for item in items:
            await self._repo.add_item(
                order_id=order.id,
                product_name=item["name"],
                quantity=item["qty"],
                unit_price=Decimal(str(item["unit_price"])),
            )
        await self._db.commit()

        await set_order_session(
            tenant_id,
            customer_phone,
            {
                "state": AWAITING_CUSTOMER_CONFIRMATION,
                "order_id": order.id,
                "items": items,
                "total": total,
            },
        )
        body_text, buttons = wa.order_summary_interactive(items, total, trader_name)
        await self._reply_interactive(
            phone=customer_phone,
            tenant_id=tenant_id,
            event_id=f"order.cart_summary.{order.id}",
            body_text=body_text,
            buttons=buttons,
            channel_tenant_id=channel_tenant_id,
        )
        logger.info(
            "Cart order created order_id=%s customer=%s total=%s",
            order.id,
            customer_phone,
            total,
        )

    async def handle_trader_command(
        self,
        *,
        tenant_id: str,
        trader_phone: str,
        message: str,
        message_id: str,
        trader: dict[str, Any],
        channel_tenant_id: str | None = None,
        image_bytes: bytes | None = None,
    ) -> None:
        """
        Process a WhatsApp command from the store owner.

        Order commands:
            CONFIRM <ref>    INQUIRY -> CONFIRMED, notify customer
            CANCEL  <ref>    INQUIRY/CONFIRMED -> FAILED, notify customer
            PAID    <ref>    CONFIRMED -> PAID
            DELIVERED <ref>  CONFIRMED/PAID -> COMPLETED

        Catalogue commands:
            ADD <product> <price>     Add a product
            REMOVE <product>          Remove a product
            PRICE <product> <price>   Update a product's price
            CATALOGUE                 View all products
            MENU                      Show interactive menu

        Interactive menu taps:
            MENU_ADD, MENU_REMOVE, MENU_PRICE, MENU_CATALOGUE, MENU_STORE, MENU_HELP

        Any other text shows the interactive menu.
        """
        from app.modules.orders.nlp import _layer1
        from app.modules.orders.session import (
            get_trader_session,
            set_trader_session,
            clear_trader_session,
            TRADER_AWAITING_ADD,
            TRADER_AWAITING_REMOVE,
            TRADER_AWAITING_PRICE_SELECT,
            TRADER_AWAITING_PRICE_VALUE,
        )

        trader_name: str = trader.get("business_name", "the trader")
        catalogue: dict[str, int] = trader.get("catalogue", {})
        store_slug: str = trader.get("store_slug", "")

        # ── Check for active trader session (multi-step flows) ────────────────
        tsession = await get_trader_session(trader_phone)
        if tsession:
            handled = await self._handle_trader_session(
                tsession=tsession,
                trader_phone=trader_phone,
                message=message,
                message_id=message_id,
                trader=trader,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
                image_bytes=image_bytes,
            )
            if handled:
                return

        # ── Parse the message ─────────────────────────────────────────────────
        result = _layer1(message)
        stripped = message.strip().upper()

        # ── Handle menu list taps (MENU_*) ────────────────────────────────────
        if stripped.startswith("MENU_"):
            await self._handle_menu_tap(
                tap=stripped,
                trader_phone=trader_phone,
                message_id=message_id,
                trader=trader,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
            return

        # ── Handle remove list tap (RM_*) ─────────────────────────────────────
        if stripped.startswith("RM_"):
            suffix = message.strip()[3:]  # preserve original case
            # Pagination: RM_NEXT_2, RM_PREV_1
            if stripped.startswith("RM_NEXT_") or stripped.startswith("RM_PREV_"):
                try:
                    page = int(suffix.split("_")[-1])
                except (IndexError, ValueError):
                    page = 1
                body, btn, sections = wa.remove_product_list(catalogue, page=page)
                await self._reply_list(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.remove_picker_p{page}.{message_id}",
                    body_text=body,
                    button_label=btn,
                    sections=sections,
                    channel_tenant_id=channel_tenant_id,
                )
                return
            # Product tap — remove directly
            await self._do_remove_product(
                trader_phone=trader_phone,
                product_name=suffix,
                message_id=message_id,
                trader=trader,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
            return

        # ── Handle price list tap (PR_*) ──────────────────────────────────────
        if stripped.startswith("PR_"):
            suffix = message.strip()[3:]
            # Pagination: PR_NEXT_2, PR_PREV_1
            if stripped.startswith("PR_NEXT_") or stripped.startswith("PR_PREV_"):
                try:
                    page = int(suffix.split("_")[-1])
                except (IndexError, ValueError):
                    page = 1
                body, btn, sections = wa.price_product_list(catalogue, page=page)
                await self._reply_list(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.price_picker_p{page}.{message_id}",
                    body_text=body,
                    button_label=btn,
                    sections=sections,
                    channel_tenant_id=channel_tenant_id,
                )
                return
            # Product tap — prompt for new price
            product_name = suffix
            price = catalogue.get(product_name)
            if price is None:
                for cat_name, cat_price in catalogue.items():
                    if cat_name.lower() == product_name.lower():
                        product_name = cat_name
                        price = cat_price
                        break
            if price is not None:
                await set_trader_session(trader_phone, {
                    "state": TRADER_AWAITING_PRICE_VALUE,
                    "product_name": product_name,
                })
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.price_prompt.{message_id}",
                    text=wa.price_enter_prompt(product_name, price),
                    channel_tenant_id=channel_tenant_id,
                )
            else:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.price_notfound.{message_id}",
                    text=wa.product_not_found(product_name),
                    channel_tenant_id=channel_tenant_id,
                )
            return

        # ── Handle order action tap (ORDACT_*) ────────────────────────────
        if stripped.startswith("ORDACT_"):
            order_ref = message.strip()[7:]  # preserve case
            order = await self._repo.get_by_ref_prefix(ref_prefix=order_ref.lower())
            if not order:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.ordact_notfound.{message_id}",
                    text=wa.order_not_found_to_trader(order_ref),
                    channel_tenant_id=channel_tenant_id,
                )
                return
            total = int(order.amount or 0)
            cust_phone = order.customer_phone or "unknown"
            ref_lower = order_ref.lower()
            # Show context-appropriate buttons based on order state
            if order.state == OrderState.INQUIRY:
                body, buttons = wa.order_action_buttons(
                    ref_lower, cust_phone, total, order.state, order.is_credit
                )
                await self._reply_interactive(
                    phone=trader_phone, tenant_id=tenant_id,
                    event_id=f"trader.ordact.{message_id}",
                    body_text=body, buttons=buttons,
                    channel_tenant_id=channel_tenant_id,
                )
            elif order.state == OrderState.CONFIRMED:
                body, buttons = wa.pending_order_actions(ref_lower, cust_phone, total)
                await self._reply_interactive(
                    phone=trader_phone, tenant_id=tenant_id,
                    event_id=f"trader.ordact.{message_id}",
                    body_text=body, buttons=buttons,
                    channel_tenant_id=channel_tenant_id,
                )
            elif order.state == OrderState.PAID:
                body, buttons = wa.order_action_buttons(
                    ref_lower, cust_phone, total, order.state, order.is_credit
                )
                await self._reply_interactive(
                    phone=trader_phone, tenant_id=tenant_id,
                    event_id=f"trader.ordact.{message_id}",
                    body_text=body, buttons=buttons,
                    channel_tenant_id=channel_tenant_id,
                )
            else:
                await self._reply(
                    phone=trader_phone, tenant_id=tenant_id,
                    event_id=f"trader.ordact_done.{message_id}",
                    text=f"Order {order_ref} is already {order.state}.",
                    channel_tenant_id=channel_tenant_id,
                )
            return

        # ── Handle category list tap (CAT_*) ────────────────────────────────
        if stripped.startswith("CAT_"):
            new_category = message.strip()[4:]  # preserve original case
            await self._do_change_category(
                trader_phone=trader_phone,
                new_category=new_category,
                message_id=message_id,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
            return

        # ── Catalogue commands (typed) ────────────────────────────────────────
        if result.intent == TRADER_ADD:
            await self._do_add_products(
                trader_phone=trader_phone,
                items=result.items,
                message_id=message_id,
                trader=trader,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
            return

        if result.intent == TRADER_REMOVE:
            await self._do_remove_products(
                trader_phone=trader_phone,
                names=[item["name"] for item in result.items],
                message_id=message_id,
                trader=trader,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
            return

        if result.intent == TRADER_PRICE:
            await self._do_update_prices(
                trader_phone=trader_phone,
                items=result.items,
                message_id=message_id,
                trader=trader,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
            return

        if result.intent == TRADER_CATALOGUE:
            if not catalogue:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.catalogue.{message_id}",
                    text=wa.catalogue_list(catalogue, trader_name),
                    channel_tenant_id=channel_tenant_id,
                )
            else:
                body, btn, sections = wa.catalogue_picker(catalogue, trader_name)
                await self._reply_list(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.catalogue.{message_id}",
                    body_text=body,
                    button_label=btn,
                    sections=sections,
                    channel_tenant_id=channel_tenant_id,
                )
            return

        if result.intent == TRADER_CATEGORY:
            current_cat = trader.get("business_category", "")
            body, btn, sections = wa.category_picker(current_cat)
            await self._reply_list(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.category_picker.{message_id}",
                body_text=body,
                button_label=btn,
                sections=sections,
                channel_tenant_id=channel_tenant_id,
            )
            return

        if result.intent == TRADER_PRICELIST:
            from app.modules.orders.session import set_trader_session, TRADER_AWAITING_PRICELIST_PHOTO
            await set_trader_session(trader_phone, {
                "state": TRADER_AWAITING_PRICELIST_PHOTO,
                "ocr_texts": [],
                "photo_count": 0,
            })
            body, buttons = wa.pricelist_prompt()
            await self._reply_interactive(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.pricelist_prompt.{message_id}",
                body_text=body,
                buttons=buttons,
                channel_tenant_id=channel_tenant_id,
            )
            return

        if result.intent == TRADER_DEBT:
            item = result.items[0]
            await self._do_create_debt(
                trader_phone=trader_phone,
                customer_name=item["name"],
                amount=item["unit_price"],
                message_id=message_id,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
            return

        if result.intent == TRADER_PAID_DEBT:
            item = result.items[0]
            await self._do_settle_debt(
                trader_phone=trader_phone,
                customer_name=item["name"],
                amount=item["unit_price"],
                message_id=message_id,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
            return

        if result.intent == TRADER_WHO_OWES_ME:
            await self._do_list_debts(
                trader_phone=trader_phone,
                message_id=message_id,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
            return

        if result.intent == TRADER_ORDERS:
            await self._do_list_pending_orders(
                trader_phone=trader_phone,
                message_id=message_id,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
            return

        if result.intent == TRADER_MENU:
            await self._send_trader_menu(
                trader_phone=trader_phone,
                message_id=message_id,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
            return

        # ── Order commands ────────────────────────────────────────────────────
        if result.intent not in (
            TRADER_CONFIRM, TRADER_CANCEL, TRADER_PAID, TRADER_CREDIT, TRADER_DELIVERED
        ):
            # Check if trader is replying to a pending image inquiry
            handled = await self._handle_image_inquiry_reply(
                trader_phone=trader_phone,
                message=message,
                message_id=message_id,
                trader=trader,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
            if handled:
                return

            # Show interactive menu instead of text command guide
            await self._send_trader_menu(
                trader_phone=trader_phone,
                message_id=message_id,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
            return

        ref = result.order_ref or ""
        # Look up by ref prefix only — no tenant_id filter.  The 8-char UUID
        # prefix is unique enough, and the tenant_id on the order may differ
        # from the trader's current tenant (platform vs dedicated tenant after
        # first dashboard login).
        order = await self._repo.get_by_ref_prefix(ref_prefix=ref)
        if order is None:
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"order.not_found.{message_id}",
                text=wa.order_not_found_to_trader(ref),
                channel_tenant_id=channel_tenant_id,
            )
            return

        customer_phone: str = order.customer_phone or ""

        if result.intent == TRADER_CONFIRM:
            try:
                await self._transition(order, OrderState.CONFIRMED)
                await self._db.commit()
            except ConflictError as exc:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"order.confirm_err.{message_id}",
                    text=f"Cannot confirm order {ref}: {exc}",
                    channel_tenant_id=channel_tenant_id,
                )
                return
            body_text, buttons = wa.order_confirmed_to_trader(ref)
            await self._reply_interactive(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"order.confirmed_trader.{order.id}",
                body_text=body_text,
                buttons=buttons,
                channel_tenant_id=channel_tenant_id,
            )
            if customer_phone:
                total = int(order.amount or 0)
                await self._reply(
                    phone=customer_phone,
                    tenant_id=tenant_id,
                    event_id=f"order.confirmed_customer.{order.id}",
                    text=wa.order_confirmed_to_customer(trader_name, total),
                    channel_tenant_id=channel_tenant_id,
                )
            logger.info("Trader confirmed order_id=%s ref=%s", order.id, ref)

        elif result.intent == TRADER_CANCEL:
            try:
                await self._transition(order, OrderState.FAILED)
                await self._db.commit()
            except ConflictError as exc:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"order.cancel_err.{message_id}",
                    text=f"Cannot cancel order {ref}: {exc}",
                    channel_tenant_id=channel_tenant_id,
                )
                return
            await clear_order_session(tenant_id, customer_phone)
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"order.cancelled_trader.{order.id}",
                text=wa.order_cancelled_to_trader(ref),
                channel_tenant_id=channel_tenant_id,
            )
            if customer_phone:
                await self._reply(
                    phone=customer_phone,
                    tenant_id=tenant_id,
                    event_id=f"order.cancelled_customer.{order.id}",
                    text=wa.order_cancelled_to_customer(trader_name),
                    channel_tenant_id=channel_tenant_id,
                )
            logger.info("Trader cancelled order_id=%s ref=%s", order.id, ref)

        elif result.intent == TRADER_PAID:
            try:
                await self._transition(order, OrderState.PAID)
                await self._db.commit()
            except ConflictError as exc:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"order.paid_err.{message_id}",
                    text=f"Cannot mark order {ref} as paid: {exc}",
                    channel_tenant_id=channel_tenant_id,
                )
                return
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"order.paid_trader.{order.id}",
                text=wa.order_paid_to_trader(ref),
                channel_tenant_id=channel_tenant_id,
            )
            logger.info("Trader marked order PAID order_id=%s ref=%s", order.id, ref)

        elif result.intent == TRADER_CREDIT:
            # Create a credit sale linked to this order
            from decimal import Decimal as D
            from app.modules.credit_sales.models import CreditSale

            total = int(order.amount or 0)
            cust_phone = order.customer_phone or "unknown"

            try:
                async with async_session_factory.begin() as cs_session:
                    credit_sale = CreditSale(
                        tenant_id=order.tenant_id,
                        order_id=order.id,
                        customer_name=f"+{cust_phone}" if cust_phone != "unknown" else "Unknown",
                        amount=D(str(total)),
                        currency=order.currency or "NGN",
                    )
                    cs_session.add(credit_sale)
                # Mark the order as credit
                order.is_credit = True
                await self._db.commit()
            except Exception as exc:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"order.credit_err.{message_id}",
                    text=f"Cannot create credit for order {ref}: {exc}",
                    channel_tenant_id=channel_tenant_id,
                )
                return

            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"order.credit_trader.{order.id}",
                text=wa.order_credit_to_trader(ref, cust_phone, total),
                channel_tenant_id=channel_tenant_id,
            )
            logger.info("Trader marked order CREDIT order_id=%s ref=%s", order.id, ref)

        elif result.intent == TRADER_DELIVERED:
            # Accept CONFIRMED -> COMPLETED or PAID -> COMPLETED
            try:
                await self._transition(order, OrderState.COMPLETED)
                await self._db.commit()
            except ConflictError as exc:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"order.deliver_err.{message_id}",
                    text=f"Cannot mark order {ref} as delivered: {exc}",
                    channel_tenant_id=channel_tenant_id,
                )
                return
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"order.delivered_trader.{order.id}",
                text=wa.order_delivered_to_trader(ref),
                channel_tenant_id=channel_tenant_id,
            )
            logger.info("Trader marked order DELIVERED order_id=%s ref=%s", order.id, ref)

    async def _reply(
        self,
        *,
        phone: str,
        tenant_id: str,
        event_id: str,
        text: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        """
        Send a WhatsApp message using an independent DB session.

        channel_tenant_id: when set, outbound WhatsApp credentials are fetched
        from this tenant (the platform tenant) instead of tenant_id.  Lets
        multi-trader orders be stored under the trader's tenant while all
        outbound messages still go through the shared platform number.

        Failures are logged but never bubble up — a bad send must never corrupt
        order state or crash the event handler loop.
        """
        if not phone:
            logger.warning("_reply called with empty phone for event_id=%s", event_id)
            return
        try:
            async with async_session_factory.begin() as session:
                svc = NotificationService(session)
                await svc.send_message(
                    tenant_id=tenant_id,
                    event_id=event_id,
                    recipient=phone,
                    message_text=text,
                    channel="whatsapp",
                    channel_tenant_id=channel_tenant_id,
                )
        except Exception as exc:
            logger.error(
                "Order reply failed phone=%s event_id=%s: %s",
                phone,
                event_id,
                exc,
            )

    async def _reply_interactive(
        self,
        *,
        phone: str,
        tenant_id: str,
        event_id: str,
        body_text: str,
        buttons: list[dict[str, str]],
        channel_tenant_id: str | None = None,
        context_message_id: str | None = None,
    ) -> None:
        """
        Send a WhatsApp interactive button message using an independent DB session.

        context_message_id: when set, the message is displayed as a reply to
        the specified wamid (shows a quoted thumbnail of the original message).
        Same error-swallowing pattern as _reply — failures never crash the handler.
        """
        if not phone:
            logger.warning("_reply_interactive called with empty phone for event_id=%s", event_id)
            return
        try:
            async with async_session_factory.begin() as session:
                svc = NotificationService(session)
                await svc.send_interactive(
                    tenant_id=tenant_id,
                    event_id=event_id,
                    recipient=phone,
                    body_text=body_text,
                    buttons=buttons,
                    channel="whatsapp",
                    channel_tenant_id=channel_tenant_id,
                    context_message_id=context_message_id,
                )
        except Exception as exc:
            logger.error(
                "Order interactive reply failed phone=%s event_id=%s: %s",
                phone,
                event_id,
                exc,
            )

    async def _reply_list(
        self,
        *,
        phone: str,
        tenant_id: str,
        event_id: str,
        body_text: str,
        button_label: str,
        sections: list[dict],
        channel_tenant_id: str | None = None,
    ) -> None:
        """
        Send a WhatsApp list picker message using an independent DB session.

        Same error-swallowing pattern as _reply — failures never crash the handler.
        """
        if not phone:
            logger.warning("_reply_list called with empty phone for event_id=%s", event_id)
            return
        try:
            async with async_session_factory.begin() as session:
                svc = NotificationService(session)
                await svc.send_list(
                    tenant_id=tenant_id,
                    event_id=event_id,
                    recipient=phone,
                    body_text=body_text,
                    button_label=button_label,
                    sections=sections,
                    channel="whatsapp",
                    channel_tenant_id=channel_tenant_id,
                )
        except Exception as exc:
            logger.error(
                "Order list reply failed phone=%s event_id=%s: %s",
                phone,
                event_id,
                exc,
            )

    async def _reply_image(
        self,
        *,
        phone: str,
        tenant_id: str,
        event_id: str,
        media_id: str,
        caption: str | None = None,
        channel_tenant_id: str | None = None,
    ) -> str | None:
        """
        Forward a WhatsApp image using an independent DB session.

        Returns the wamid of the sent message (for reply-to chaining), or None.
        Same error-swallowing pattern as _reply — failures never crash the handler.
        """
        if not phone:
            logger.warning("_reply_image called with empty phone for event_id=%s", event_id)
            return None
        try:
            async with async_session_factory.begin() as session:
                svc = NotificationService(session)
                return await svc.send_image(
                    tenant_id=tenant_id,
                    event_id=event_id,
                    recipient=phone,
                    media_id=media_id,
                    caption=caption,
                    channel="whatsapp",
                    channel_tenant_id=channel_tenant_id,
                )
        except Exception as exc:
            logger.error(
                "Order image reply failed phone=%s event_id=%s: %s",
                phone,
                event_id,
                exc,
            )
            return None

    # ── List query ────────────────────────────────────────────────────────────

    async def list_orders(
        self,
        *,
        tenant_id: str | None,
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
        from app.modules.orders.schemas import OrderItemOut

        items = [
            OrderListItem(
                id=order.id,
                conversation_id=order.conversation_id,
                customer_id=order.customer_id,
                customer_phone=order.customer_phone,
                is_credit=order.is_credit,
                state=order.state,
                amount=order.amount,
                currency=order.currency,
                created_at=order.created_at,
                updated_at=order.updated_at,
                item_count=count,
                items=[OrderItemOut.model_validate(i) for i in order.items],
            )
            for order, count in rows
        ]
        return OrderListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )
