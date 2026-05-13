"""
app/modules/orders/service.py

OrderService — orchestrates the order lifecycle.

WhatsApp-driven entry points (Feature 2):
  handle_inbound_customer_message() — parses customer orders and manages the
      customer confirmation flow via Redis session.
  handle_trader_command() — interprets CONFIRM/CANCEL/PAID/CREDIT commands
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
    TRADER_MENU,
    TRADER_BANK,
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
from app.modules.orders.nlp import CHITCHAT, IGNORE, NEGOTIATION, PAYMENT_SENT
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

        Emits both order.state_changed and order.paid events.
        Does NOT commit — the caller owns the transaction.
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

        if order.state in (OrderState.PAID, OrderState.PAID):
            logger.info(
                "handle_payment_confirmed: order already %s order_id=%s — idempotent",
                order.state, order_id,
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
        order = await self._transition(order, OrderState.PAID)
        await self._db.commit()
        return await self._reload(order.id)

    async def handle_credit_sale_resolved(
        self, *, order_id: str, tenant_id: str
    ) -> Order | None:
        """
        Transition an order to PAID when its linked credit sale is settled
        or written off.

        Accepts orders in CONFIRMED state (CONFIRMED → PAID is
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

        if order.state in (OrderState.PAID, OrderState.FAILED):
            logger.info(
                "handle_credit_sale_resolved: order already terminal order_id=%s state=%s",
                order_id,
                order.state,
            )
            return order

        try:
            order = await self._transition(order, OrderState.PAID)
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
        customer_name: str | None = None,
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

        # ── Post-order quiet mode: only respond to clear order intents ────
        from app.modules.orders.session import is_quiet_mode
        if await is_quiet_mode(tenant_id, customer_phone):
            # Quick check using Layer 1 only (no Claude call — instant, zero cost)
            from app.modules.orders.nlp import _layer1
            quick = _layer1(message)
            # Let through anything that looks intentional: order keywords,
            # negotiation, payment, YES/NO. Only block pure noise (UNKNOWN with 0 confidence).
            if quick.intent == UNKNOWN and quick.confidence == 0.0:
                logger.debug("Quiet mode: dropping message from %s", customer_phone)
                return

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
                    customer_name=customer_name,
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
                from app.modules.orders.session import set_quiet_mode
                await set_quiet_mode(tenant_id, customer_phone)
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
                from app.modules.orders.session import set_quiet_mode
                await set_quiet_mode(tenant_id, customer_phone)
                return

            # Customer sent something else — check if it's a new negotiation
            from app.modules.orders.nlp import smart_parse_customer_message, NEGOTIATION as _NEG
            counter_check = await smart_parse_customer_message(
                message, category=category, catalogue=catalogue,
            )
            if counter_check.intent == _NEG:
                # Multi-round: customer is countering. Clear confirmation, start new round.
                from app.modules.orders.session import set_pending_negotiation

                offered_price = counter_check.items[0]["unit_price"] if counter_check.items else None
                trader_phone_str: str = trader.get("phone_number", "")
                items_for_neg = session.get("items", [])
                original_price = session.get("total", 0)

                await clear_order_session(tenant_id, customer_phone)

                await self._reply(
                    phone=customer_phone,
                    tenant_id=tenant_id,
                    event_id=f"order.neg_hold.{message_id}",
                    text=wa.negotiation_hold_customer(),
                    channel_tenant_id=channel_tenant_id,
                )

                if offered_price and original_price and trader_phone_str:
                    product_name = items_for_neg[0].get("name", "the item") if items_for_neg else "the item"
                    body, buttons = wa.negotiation_to_trader_with_price(
                        customer_phone=customer_phone,
                        customer_name=customer_name,
                        product_name=product_name,
                        original_price=original_price,
                        offered_price=offered_price,
                    )
                    await self._reply_interactive(
                        phone=trader_phone_str,
                        tenant_id=tenant_id,
                        event_id=f"order.neg_round.{message_id}",
                        body_text=body,
                        buttons=buttons,
                        channel_tenant_id=channel_tenant_id,
                    )
                    await set_pending_negotiation(
                        trader_phone_str,
                        customer_phone,
                        {
                            "offered_price": offered_price,
                            "original_price": original_price,
                            "product_name": product_name,
                            "items": items_for_neg,
                            "order_id": session.get("order_id"),
                            "tenant_id": tenant_id,
                            "channel_tenant_id": channel_tenant_id or "",
                        },
                    )
                return

            # Not a negotiation — re-show the summary
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
            original = session.get("original_message", "")
            bot_reply = session.get("bot_reply", "")
            numbered_items: list[dict[str, Any]] = session.get("numbered_items", [])

            # Quick-pick: customer replies with a number matching a numbered list
            import re as _pick_re
            num_match = _pick_re.match(r"^\s*(\d{1,2})\s*$", message.strip())
            if num_match and numbered_items:
                picked_num = int(num_match.group(1))
                picked = next((it for it in numbered_items if it["index"] == picked_num), None)
                if picked:
                    from app.modules.orders.nlp import ParseResult
                    result = ParseResult(
                        intent=ORDER,
                        items=[{"name": picked["name"], "qty": 1, "unit_price": picked["price"]}],
                        confidence=1.0,
                    )
                    await clear_order_session(tenant_id, customer_phone)
                    logger.info("Quick-pick: customer chose #%d -> %s", picked_num, picked["name"])
                else:
                    await self._reply(
                        phone=customer_phone, tenant_id=tenant_id,
                        event_id=f"order.pick_invalid.{message_id}",
                        text=f"There's no item #{picked_num} in the list. Please pick a number from the list, or tell me what you want.",
                        channel_tenant_id=channel_tenant_id,
                    )
                    return
            else:
                # Re-parse with full conversation context (original + bot reply + new message)
                extra_history: list[dict[str, str]] = []
                if original:
                    extra_history.append({"role": "user", "content": original})
                if bot_reply:
                    extra_history.append({"role": "assistant", "content": bot_reply})

                try:
                    result = await self._smart_parse(
                        message, category, catalogue, conversation_id,
                        extra_history=extra_history,
                    )
                except Exception as exc:
                    logger.error("Smart parse failed (clarification): %s", exc, exc_info=True)
                    from app.modules.orders.nlp import ParseResult
                    result = ParseResult(intent=UNKNOWN, confidence=0.0)
                await clear_order_session(tenant_id, customer_phone)
        else:
            try:
                result = await self._smart_parse(message, category, catalogue, conversation_id)
            except Exception as exc:
                logger.error("Smart parse failed: %s", exc, exc_info=True)
                from app.modules.orders.nlp import ParseResult
                result = ParseResult(intent=UNKNOWN, confidence=0.0)

        # ── No session (or just resolved clarification): fresh order parse ────
        logger.info(
            "Smart parse result: intent=%s items=%d clarify=%s customer=%s",
            result.intent, len(result.items), result.clarification_needed, customer_phone,
        )

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

        # ── Ignore: no response needed ─────────────────────────────────────
        if result.intent == IGNORE:
            return

        # ── Chitchat: friendly reply, no order flow ────────────────────────
        if result.intent == CHITCHAT:
            reply_text = result.clarification_question or "Hi! What would you like to order?"
            await self._reply(
                phone=customer_phone,
                tenant_id=tenant_id,
                event_id=f"order.chitchat.{message_id}",
                text=reply_text,
                channel_tenant_id=channel_tenant_id,
            )
            return

        # ── Payment sent detected ─────────────────────────────────────────
        if result.intent == PAYMENT_SENT:
            await self._handle_payment_sent(
                tenant_id=tenant_id,
                customer_phone=customer_phone,
                customer_name=customer_name,
                message_id=message_id,
                trader=trader,
                channel_tenant_id=channel_tenant_id,
            )
            return

        # ── Negotiation detected ────────────────────────────────────────────
        if result.intent == NEGOTIATION:
            from app.modules.orders.session import set_pending_negotiation

            offered_price = result.items[0]["unit_price"] if result.items else None
            trader_phone: str = trader.get("phone_number", "")

            # Notify customer — they are FREE to keep chatting
            await self._reply(
                phone=customer_phone,
                tenant_id=tenant_id,
                event_id=f"order.neg_hold.{message_id}",
                text=wa.negotiation_hold_customer(),
                channel_tenant_id=channel_tenant_id,
            )

            # Find the product being negotiated
            product_name = "the item"
            original_price = 0
            items = []
            order_id = None
            if session and session.get("items"):
                items = session["items"]
                first_item = items[0]
                product_name = first_item.get("name", "the item")
                original_price = first_item.get("unit_price", 0)
                order_id = session.get("order_id")

            if offered_price and original_price and trader_phone:
                # Specific price offer — send interactive to trader
                body, buttons = wa.negotiation_to_trader_with_price(
                    customer_phone=customer_phone,
                    customer_name=customer_name,
                    product_name=product_name,
                    original_price=original_price,
                    offered_price=offered_price,
                )
                await self._reply_interactive(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"order.neg_escalate.{message_id}",
                    body_text=body,
                    buttons=buttons,
                    channel_tenant_id=channel_tenant_id,
                )
                # Store as pending negotiation — does NOT block the customer
                await set_pending_negotiation(
                    trader_phone,
                    customer_phone,
                    {
                        "offered_price": offered_price,
                        "original_price": original_price,
                        "product_name": product_name,
                        "items": items,
                        "order_id": order_id,
                        "tenant_id": tenant_id,
                        "channel_tenant_id": channel_tenant_id or "",
                    },
                )
            elif trader_phone:
                # General negotiation — notify trader (no buttons, just text)
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"order.neg_general.{message_id}",
                    text=wa.negotiation_to_trader_general(
                        customer_phone=customer_phone,
                        customer_name=customer_name,
                        product_name=product_name,
                        price=original_price,
                    ),
                    channel_tenant_id=channel_tenant_id,
                )
            # Clear the customer's order session so they're free
            if session:
                await clear_order_session(tenant_id, customer_phone)
            return

        if result.intent == UNKNOWN or (result.intent == ORDER and not result.items):
            if result.clarification_needed and result.clarification_question:
                reply_text = result.clarification_question

                # Extract numbered items from the reply for quick-pick
                import re as _cl_re
                numbered_items: list[dict[str, Any]] = []
                for m in _cl_re.finditer(r"(\d+)\.\s+(.+?)\s*[-\u2013]\s*N([\d,]+)", reply_text):
                    numbered_items.append({
                        "index": int(m.group(1)),
                        "name": m.group(2).strip(),
                        "price": int(m.group(3).replace(",", "")),
                    })

                # Save context including bot reply and numbered items
                await set_order_session(
                    tenant_id,
                    customer_phone,
                    {
                        "state": AWAITING_CLARIFICATION,
                        "original_message": message,
                        "bot_reply": reply_text,
                        "numbered_items": numbered_items,
                    },
                )
                await self._reply(
                    phone=customer_phone,
                    tenant_id=tenant_id,
                    event_id=f"order.clarify.{message_id}",
                    text=wa.ask_clarification(reply_text),
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
            if not item.get("unit_price"):
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
            customer_name=customer_name,
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
        customer_name: str | None = None,
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

        # ── Check for payment screenshot: if customer has a CONFIRMED order,
        #    treat image as payment receipt/screenshot ──────────────────────
        confirmed_order = await self._repo.get_open_order_by_customer_phone(
            customer_phone=customer_phone,
            tenant_id=tenant_id,
        )
        if confirmed_order and confirmed_order.state == OrderState.CONFIRMED:
            await self._handle_payment_sent(
                tenant_id=tenant_id,
                customer_phone=customer_phone,
                customer_name=customer_name,
                message_id=message_id,
                trader=trader,
                channel_tenant_id=channel_tenant_id,
                has_screenshot=True,
            )
            return

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

            # Upload the image to R2 immediately (before trader replies)
            # so it's available when the trader names the product
            temp_image_url = ""
            try:
                from app.infra.storage import upload_product_image as _r2_upload
                temp_name = f"_pending_{image_hash or customer_phone}"
                url = await _r2_upload(
                    trader_phone=trader_phone,
                    product_name=temp_name,
                    image_bytes=image_bytes,
                )
                temp_image_url = url or ""
            except Exception as exc:
                logger.warning("R2 upload for pending inquiry failed: %s", exc)

            # Store pending inquiry so trader's price reply can be learned
            await set_pending_image_inquiry(
                trader_phone,
                {
                    "customer_phone": customer_phone,
                    "image_hash": image_hash or "",
                    "image_url": temp_image_url,
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

        # Save product image passively (if we uploaded it during the inquiry)
        pending_image_url: str = pending.get("image_url", "")
        if pending_image_url:
            try:
                from app.modules.orders.product_images import ProductImageRepository
                async with async_session_factory.begin() as img_session:
                    img_repo = ProductImageRepository(img_session)
                    await img_repo.upsert(
                        trader_phone=trader_phone,
                        product_name=product_name,
                        image_url=pending_image_url,
                        image_hash=pending_image_hash or None,
                    )
                logger.info(
                    "Passive product image saved: trader=%s product=%s",
                    trader_phone, product_name,
                )
            except Exception as exc:
                logger.warning("Passive image save failed: %s", exc)

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
        elif tap == "MENU_BANK":
            from app.modules.orders.session import set_trader_session, TRADER_AWAITING_BANK_DETAILS
            bank_name = trader.get("bank_name", "")
            if bank_name:
                text = wa.bank_details_current(
                    bank_name, trader.get("bank_account_number", ""),
                    trader.get("bank_account_name", ""),
                )
            else:
                text = wa.bank_details_not_set()
            await self._reply(
                phone=trader_phone, tenant_id=tenant_id,
                event_id=f"trader.bank_menu.{message_id}",
                text=text, channel_tenant_id=channel_tenant_id,
            )
            await set_trader_session(trader_phone, {"state": TRADER_AWAITING_BANK_DETAILS})
        elif tap == "MENU_ORDERS":
            await self._do_list_pending_orders(
                trader_phone=trader_phone,
                message_id=message_id,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
        elif tap == "MENU_DEBTS":
            await self._do_list_debts(
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
            TRADER_AWAITING_COUNTER_PRICE,
            TRADER_AWAITING_BANK_DETAILS,
            TRADER_AWAITING_BANK_CONFIRM,
            TRADER_AWAITING_CREDIT_PARTIAL,
            TRADER_AWAITING_PHOTO_PRODUCT,
        )

        state = tsession.get("state", "")

        if state == TRADER_AWAITING_PHOTO_PRODUCT:
            # Waiting for trader to pick which product the photo is for
            # This can come from a PHOT_ list tap or typed product name
            await clear_trader_session(trader_phone)
            product_name = message.strip()
            # Handle PHOT_ prefix from list picker
            if product_name.upper().startswith("PHOT_"):
                product_name = product_name[5:]

            catalogue = trader.get("catalogue", {})
            # Case-insensitive match
            matched_name: str | None = None
            matched_price: int = 0
            for key, val in catalogue.items():
                if key.lower() == product_name.lower():
                    matched_name = key
                    matched_price = val
                    break
            if not matched_name:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.photo_nomatch.{message_id}",
                    text=wa.product_not_found(product_name),
                    channel_tenant_id=channel_tenant_id,
                )
                return True

            # Retrieve stored image bytes from session and upload
            import base64
            img_b64 = tsession.get("image_b64", "")
            if img_b64:
                img_bytes = base64.b64decode(img_b64)
                await self._save_product_image(
                    trader_phone=trader_phone,
                    product_name=matched_name,
                    image_bytes=img_bytes,
                )
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.photo_saved.{message_id}",
                    text=wa.product_photo_saved(matched_name, matched_price),
                    channel_tenant_id=channel_tenant_id,
                )
            return True

        if state == TRADER_AWAITING_BANK_DETAILS:
            await clear_trader_session(trader_phone)
            # Parse "GTBank 0123456789" — bank name (words) + account number (digits)
            text = message.strip()
            m = _re.match(r"^(.+?)\s+(\d{10})\s*$", text)
            if not m:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.bank_invalid.{message_id}",
                    text=(
                        "I didn't understand that. Type your bank name and "
                        "10-digit account number.\n\nFor example: _GTBank 0123456789_"
                    ),
                    channel_tenant_id=channel_tenant_id,
                )
                return True

            bank_name = m.group(1).strip()
            account_number = m.group(2)

            # Try to verify account name via Paystack
            from app.infra.paystack import resolve_bank_code, resolve_account_name
            from app.modules.orders.session import TRADER_AWAITING_BANK_CONFIRM

            bank_code = resolve_bank_code(bank_name)
            if bank_code is None:
                # Bank not recognised — warn but still save with business name
                account_name = trader.get("business_name", bank_name)
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.bank_unknown.{message_id}",
                    text=wa.bank_unknown_bank(bank_name),
                    channel_tenant_id=channel_tenant_id,
                )
                return True

            resolved_name = await resolve_account_name(bank_code, account_number)
            if resolved_name:
                # Ask trader to confirm the resolved account name
                await set_trader_session(trader_phone, {
                    "state": TRADER_AWAITING_BANK_CONFIRM,
                    "bank_name": bank_name,
                    "account_number": account_number,
                    "account_name": resolved_name,
                })
                body, buttons = wa.bank_verify_confirm(
                    bank_name, account_number, resolved_name,
                )
                await self._reply_interactive(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.bank_verify.{message_id}",
                    body_text=body,
                    buttons=buttons,
                    channel_tenant_id=channel_tenant_id,
                )
                return True

            # Resolve failed — save with business name as fallback
            account_name = trader.get("business_name", bank_name)
            await self._save_bank_details(
                trader_phone=trader_phone,
                bank_name=bank_name,
                account_number=account_number,
                account_name=account_name,
                message_id=message_id,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.bank_noverify.{message_id}",
                text=wa.bank_verify_failed(bank_name),
                channel_tenant_id=channel_tenant_id,
            )
            return True

        if state == TRADER_AWAITING_BANK_CONFIRM:
            await clear_trader_session(trader_phone)
            answer = message.strip().upper()
            if answer in ("YES", "BANK_YES"):
                # Trader confirmed — save bank details
                bank_name = tsession.get("bank_name", "")
                account_number = tsession.get("account_number", "")
                account_name = tsession.get("account_name", "")
                await self._save_bank_details(
                    trader_phone=trader_phone,
                    bank_name=bank_name,
                    account_number=account_number,
                    account_name=account_name,
                    message_id=message_id,
                    tenant_id=tenant_id,
                    channel_tenant_id=channel_tenant_id,
                )
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.bank_confirmed.{message_id}",
                    text=wa.bank_details_saved(bank_name, account_number, account_name),
                    channel_tenant_id=channel_tenant_id,
                )
            else:
                # Trader rejected — ask them to re-enter
                from app.modules.orders.session import TRADER_AWAITING_BANK_DETAILS as _TABD
                await set_trader_session(trader_phone, {"state": _TABD})
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.bank_retry.{message_id}",
                    text=(
                        "No problem. Type your bank name and account number again.\n\n"
                        "For example: _GTBank 0123456789_"
                    ),
                    channel_tenant_id=channel_tenant_id,
                )
            return True

        if state == TRADER_AWAITING_CREDIT_PARTIAL:
            await clear_trader_session(trader_phone)
            # Parse the partial payment amount
            cleaned = _re.sub(r"(\d),(\d)", r"\1\2", message.strip())
            numbers = _re.findall(r"\d+", cleaned)
            if not numbers:
                await self._reply(
                    phone=trader_phone, tenant_id=tenant_id,
                    event_id=f"trader.creditpart_invalid.{message_id}",
                    text="I didn't understand that. Just type the amount received (e.g. _5000_):",
                    channel_tenant_id=channel_tenant_id,
                )
                return True

            paid_amount = int(numbers[0])
            order_id = tsession.get("order_id", "")
            order_ref = tsession.get("order_ref", "")
            session_cust_name: str | None = tsession.get("customer_name") or None

            if paid_amount <= 0:
                await self._reply(
                    phone=trader_phone, tenant_id=tenant_id,
                    event_id=f"trader.creditpart_zero.{message_id}",
                    text="Amount must be greater than zero.",
                    channel_tenant_id=channel_tenant_id,
                )
                return True

            # Find and reduce the linked credit sale
            from app.modules.credit_sales.models import CreditSale, CreditSaleStatus
            from decimal import Decimal as D

            async with async_session_factory.begin() as cs_session:
                from sqlalchemy import select
                cs_result = await cs_session.execute(
                    select(CreditSale).where(
                        CreditSale.order_id == order_id,
                        CreditSale.status == CreditSaleStatus.ACTIVE,
                    )
                )
                credit_sale = cs_result.scalar_one_or_none()
                if credit_sale:
                    outstanding = int(credit_sale.amount)
                    if paid_amount >= outstanding:
                        # Full settlement
                        credit_sale.status = CreditSaleStatus.SETTLED
                        credit_sale.amount = D("0")
                        # Also mark order PAID
                        order = await self._repo.get_by_id(order_id=order_id)
                        if order and order.state == OrderState.CONFIRMED:
                            try:
                                await self._transition(order, OrderState.PAID)
                                await self._db.commit()
                            except ConflictError:
                                pass
                        await self._reply(
                            phone=trader_phone, tenant_id=tenant_id,
                            event_id=f"order.creditpart_full.{message_id}",
                            text=wa.credit_paid_in_full(order_ref, outstanding, customer_name=session_cust_name),
                            channel_tenant_id=channel_tenant_id,
                        )
                    else:
                        # Partial — reduce balance
                        remaining = outstanding - paid_amount
                        credit_sale.amount = D(str(remaining))
                        await self._reply(
                            phone=trader_phone, tenant_id=tenant_id,
                            event_id=f"order.creditpart_partial.{message_id}",
                            text=wa.credit_partial_received(order_ref, paid_amount, remaining, customer_name=session_cust_name),
                            channel_tenant_id=channel_tenant_id,
                        )
                else:
                    await self._reply(
                        phone=trader_phone, tenant_id=tenant_id,
                        event_id=f"order.creditpart_notfound.{message_id}",
                        text=f"Could not find an active credit for order {order_ref}.",
                        channel_tenant_id=channel_tenant_id,
                    )
            return True

        if state == TRADER_AWAITING_COUNTER_PRICE:
            await clear_trader_session(trader_phone)
            # Parse the counter-offer price from trader's message
            cleaned = _re.sub(r"(\d),(\d)", r"\1\2", message.strip())
            numbers = _re.findall(r"\d+", cleaned)
            if not numbers:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.neg_counter_invalid.{message_id}",
                    text="I didn't understand that. Just type the price (e.g. _7500_):",
                    channel_tenant_id=channel_tenant_id,
                )
                return True

            counter_price = int(numbers[0])
            if counter_price <= 0:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.neg_counter_invalid.{message_id}",
                    text="Price must be greater than 0. Type the price (e.g. _7500_):",
                    channel_tenant_id=channel_tenant_id,
                )
                return True

            customer_phone_for_neg = tsession.get("customer_phone", "")
            if not customer_phone_for_neg:
                return True

            trader_name = trader.get("business_name", "the trader")

            # Find the pending negotiation and resolve it
            from app.modules.orders.session import (
                get_pending_negotiation,
                clear_pending_negotiation,
            )
            neg = await get_pending_negotiation(trader_phone, customer_phone_for_neg)
            items = neg.get("items", []) if neg else []
            neg_tenant_id = neg.get("tenant_id", tenant_id) if neg else tenant_id
            neg_channel_tid = (neg.get("channel_tenant_id") or channel_tenant_id) if neg else channel_tenant_id
            if items:
                items[0]["unit_price"] = counter_price

            await clear_pending_negotiation(trader_phone, customer_phone_for_neg)

            await set_order_session(
                neg_tenant_id,
                customer_phone_for_neg,
                {
                    "state": AWAITING_CUSTOMER_CONFIRMATION,
                    "items": items,
                    "total": counter_price,
                    "order_id": neg.get("order_id") if neg else None,
                },
            )

            # Notify customer
            await self._reply(
                phone=customer_phone_for_neg,
                tenant_id=neg_tenant_id,
                event_id=f"order.neg_counter.{message_id}",
                text=wa.negotiation_counter_to_customer(trader_name, counter_price),
                channel_tenant_id=neg_channel_tid,
            )

            # Confirm to trader
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"order.neg_counter_sent.{message_id}",
                text=f"\u2705 Counter-offer of {wa._naira(counter_price)} sent. Waiting for customer to respond.",
                channel_tenant_id=channel_tenant_id,
            )

            logger.info(
                "Negotiation counter-offer: trader=%s customer=%s price=%d",
                trader_phone, customer_phone_for_neg, counter_price,
            )
            return True

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
                        text="Couldn't read that photo. \U0001f914 Try a clearer one or send another.",
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
                    "I didn't understand that. Type product name and price like:\n\n"
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
                text="I didn't understand that. Just type the new price like:\n\n_9000_",
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
                text += f"\n\nCould not find: {', '.join(not_found)}"
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
                text += f"\n\nCould not find: {', '.join(not_found)}"
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

    # ── Product image helpers ────────────────────────────────────────────

    async def _save_product_image(
        self,
        *,
        trader_phone: str,
        product_name: str,
        image_bytes: bytes,
    ) -> str | None:
        """Upload product image to R2 and save reference in DB."""
        from app.infra.storage import upload_product_image
        from app.modules.orders.product_images import ProductImageRepository
        from app.modules.onboarding.media import compute_phash

        url = await upload_product_image(
            trader_phone=trader_phone,
            product_name=product_name,
            image_bytes=image_bytes,
        )
        if not url:
            return None

        # Compute pHash for image matching
        image_hash: str | None = None
        try:
            image_hash = compute_phash(image_bytes)
        except Exception:
            pass

        async with async_session_factory.begin() as session:
            repo = ProductImageRepository(session)
            await repo.upsert(
                trader_phone=trader_phone,
                product_name=product_name,
                image_url=url,
                image_hash=image_hash,
            )

        logger.info("Product image saved: trader=%s product=%s url=%s", trader_phone, product_name, url)
        return url

    async def _handle_trader_product_photo(
        self,
        *,
        trader_phone: str,
        message: str,
        message_id: str,
        image_bytes: bytes,
        trader: dict[str, Any],
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        """Handle a product photo sent by the trader (outside any session)."""
        import base64
        from app.modules.orders.session import set_trader_session, TRADER_AWAITING_PHOTO_PRODUCT

        catalogue = trader.get("catalogue", {})
        caption = message.strip() if message and message != "[image]" else ""

        # If caption matches a product name, save directly
        if caption:
            matched_name: str | None = None
            matched_price: int = 0
            for key, val in catalogue.items():
                if caption.lower() in key.lower() or key.lower() in caption.lower():
                    matched_name = key
                    matched_price = val
                    break
            if matched_name:
                await self._save_product_image(
                    trader_phone=trader_phone,
                    product_name=matched_name,
                    image_bytes=image_bytes,
                )
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.photo_saved.{message_id}",
                    text=wa.product_photo_saved(matched_name, matched_price),
                    channel_tenant_id=channel_tenant_id,
                )
                return

        # No caption or no match — ask which product
        if not catalogue:
            return  # No catalogue, nothing to match

        result = wa.product_photo_which_product(catalogue)
        if result is None:
            return

        # Store image bytes in session (base64) so we can upload after product selection
        img_b64 = base64.b64encode(image_bytes).decode()
        # Limit to 500KB base64 to avoid Redis memory issues
        if len(img_b64) > 700_000:
            from PIL import Image
            from io import BytesIO
            img = Image.open(BytesIO(image_bytes))
            img = img.convert("RGB")
            img.thumbnail((400, 400), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=60)
            img_b64 = base64.b64encode(buf.getvalue()).decode()

        await set_trader_session(trader_phone, {
            "state": TRADER_AWAITING_PHOTO_PRODUCT,
            "image_b64": img_b64,
        })

        body, btn, sections = result
        await self._reply_list(
            phone=trader_phone,
            tenant_id=tenant_id,
            event_id=f"trader.photo_pick.{message_id}",
            body_text=body,
            button_label=btn,
            sections=sections,
            channel_tenant_id=channel_tenant_id,
        )

    # ── Bank details helper ────────────────────────────────────────────────

    async def _save_bank_details(
        self,
        *,
        trader_phone: str,
        bank_name: str,
        account_number: str,
        account_name: str,
        message_id: str,
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        """Persist bank details and bust the trader cache."""
        async with async_session_factory.begin() as session:
            repo = TraderRepository(session)
            await repo.update_bank_details(
                phone_number=trader_phone,
                bank_name=bank_name,
                bank_account_number=account_number,
                bank_account_name=account_name,
            )

        from app.modules.orders.session import cache_trader_by_phone, get_trader_by_phone_cache
        cached = await get_trader_by_phone_cache(trader_phone)
        if cached and isinstance(cached, dict) and cached:
            cached["bank_name"] = bank_name
            cached["bank_account_number"] = account_number
            cached["bank_account_name"] = account_name
            await cache_trader_by_phone(trader_phone, cached)

    # ── Payment receipt detection ────────────────────────────────────────

    async def _handle_payment_sent(
        self,
        *,
        tenant_id: str,
        customer_phone: str,
        customer_name: str | None,
        message_id: str,
        trader: dict[str, Any],
        channel_tenant_id: str | None = None,
        has_screenshot: bool = False,
    ) -> None:
        """
        Handle when a customer says they've paid or sends a payment screenshot.

        Finds the most recent CONFIRMED order for this customer+trader,
        notifies the trader with Payment Received / Not Received buttons,
        and acknowledges to the customer.
        """
        trader_name: str = trader.get("business_name", "the trader")
        trader_phone: str = trader.get("phone_number", "")

        # Find the customer's most recent confirmed order
        order = await self._repo.get_open_order_by_customer_phone(
            customer_phone=customer_phone,
            tenant_id=tenant_id,
        )

        if order is None or order.state != OrderState.CONFIRMED:
            await self._reply(
                phone=customer_phone,
                tenant_id=tenant_id,
                event_id=f"order.payment_no_order.{message_id}",
                text=wa.no_confirmed_order_for_payment(trader_name),
                channel_tenant_id=channel_tenant_id,
            )
            return

        order_ref = order.id[:8]
        total = int(order.amount or 0)

        # Notify the trader
        if trader_phone:
            body, buttons = wa.payment_receipt_to_trader(
                customer_phone=customer_phone,
                customer_name=customer_name or order.customer_name,
                amount=total,
                order_ref=order_ref,
                has_screenshot=has_screenshot,
            )
            await self._reply_interactive(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"order.payment_notify_trader.{order.id}",
                body_text=body,
                buttons=buttons,
                channel_tenant_id=channel_tenant_id,
            )

        # Acknowledge to the customer
        await self._reply(
            phone=customer_phone,
            tenant_id=tenant_id,
            event_id=f"order.payment_ack.{order.id}",
            text=wa.payment_receipt_ack_to_customer(trader_name),
            channel_tenant_id=channel_tenant_id,
        )

        logger.info(
            "Customer payment notification sent order_id=%s customer=%s screenshot=%s",
            order.id, customer_phone, has_screenshot,
        )

    # ── Smart parse helper ────────────────────────────────────────────────

    async def _smart_parse(
        self,
        message: str,
        category: str,
        catalogue: dict[str, int],
        conversation_id: str,
        extra_history: list[dict[str, str]] | None = None,
    ) -> Any:
        """Parse customer message using Claude-first smart parser with conversation context."""
        from app.modules.orders.nlp import smart_parse_customer_message

        # Fetch last 5 messages from DB for context
        history: list[dict[str, str]] = []
        try:
            from app.modules.conversation.models import Message
            from sqlalchemy import select

            async with async_session_factory() as session:
                result = await session.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at.desc())
                    .limit(5)
                )
                msgs = list(result.scalars().all())
                for m in reversed(msgs):
                    history.append({
                        "role": "assistant" if m.sender_role == "assistant" else "user",
                        "content": m.content or "",
                    })
        except Exception:
            pass  # No history is fine — Claude still works without it

        # Prepend extra history (bot replies from clarification sessions)
        if extra_history:
            history = extra_history + history

        return await smart_parse_customer_message(
            message,
            category=category,
            catalogue=catalogue,
            conversation_history=history if history else None,
        )

    # ── Negotiation helpers ─────────────────────────────────────────────────

    async def _handle_negotiation_response(
        self,
        *,
        is_accept: bool,
        customer_phone: str,
        trader_phone: str,
        trader: dict[str, Any],
        message_id: str,
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        """Handle trader's Accept/Decline response to a negotiation."""
        from app.modules.orders.session import (
            get_pending_negotiation,
            clear_pending_negotiation,
        )

        trader_name = trader.get("business_name", "the trader")

        # Look up the pending negotiation (stored by trader+customer key)
        neg = await get_pending_negotiation(trader_phone, customer_phone)
        if not neg:
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"order.neg_expired.{message_id}",
                text="This negotiation has expired or already been resolved.",
                channel_tenant_id=channel_tenant_id,
            )
            return

        offered_price = neg.get("offered_price", 0)
        original_price = neg.get("original_price", 0)
        items = neg.get("items", [])
        neg_tenant_id = neg.get("tenant_id", tenant_id)
        neg_channel_tid = neg.get("channel_tenant_id") or channel_tenant_id

        await clear_pending_negotiation(trader_phone, customer_phone)

        if is_accept:
            # Update items with accepted price
            if items and offered_price:
                items[0]["unit_price"] = offered_price
            total = offered_price if offered_price else original_price

            # Create a new order session for the customer at the negotiated price
            await set_order_session(
                neg_tenant_id,
                customer_phone,
                {
                    "state": AWAITING_CUSTOMER_CONFIRMATION,
                    "items": items,
                    "total": total,
                    "order_id": neg.get("order_id"),
                },
            )
            await self._reply(
                phone=customer_phone,
                tenant_id=neg_tenant_id,
                event_id=f"order.neg_accepted.{message_id}",
                text=wa.negotiation_accepted_to_customer(trader_name, total),
                channel_tenant_id=neg_channel_tid,
            )
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"order.neg_accepted_trader.{message_id}",
                text=f"\u2705 You accepted {wa._naira(offered_price)}. Waiting for customer to confirm.",
                channel_tenant_id=channel_tenant_id,
            )
        else:
            # Decline — offer original price to customer
            await set_order_session(
                neg_tenant_id,
                customer_phone,
                {
                    "state": AWAITING_CUSTOMER_CONFIRMATION,
                    "items": items,
                    "total": original_price,
                    "order_id": neg.get("order_id"),
                },
            )
            await self._reply(
                phone=customer_phone,
                tenant_id=neg_tenant_id,
                event_id=f"order.neg_declined.{message_id}",
                text=wa.negotiation_declined_to_customer(trader_name, original_price),
                channel_tenant_id=neg_channel_tid,
            )
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"order.neg_declined_trader.{message_id}",
                text=f"\u274c Offer declined. Customer has been offered the original price of {wa._naira(original_price)}.",
                channel_tenant_id=channel_tenant_id,
            )

        logger.info(
            "Negotiation %s: trader=%s customer=%s offered=%s original=%s",
            "accepted" if is_accept else "declined",
            trader_phone, customer_phone, offered_price, original_price,
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

            if len(debts) > 1:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.debt_ambiguous.{message_id}",
                    text=(
                        f"Found {len(debts)} active debts for *{customer_name}*.\n\n"
                        "Type _WHO OWES ME_ and tap the right one to settle."
                    ),
                    channel_tenant_id=channel_tenant_id,
                )
                return

            # Settle or partially pay the single matching debt
            from decimal import Decimal as D
            debt = debts[0]
            debt_amount = int(debt.amount)
            display_name = debt.customer_name

            if amount <= 0:
                return

            if amount >= debt_amount:
                # Full settlement
                debt.status = CreditSaleStatus.SETTLED
                is_partial = False
            else:
                # Partial payment — reduce balance
                debt.amount = D(str(debt_amount - amount))
                is_partial = True

        if is_partial:
            remaining = debt_amount - amount
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.debt_partial.{message_id}",
                text=wa.debt_partial_payment(display_name, amount, remaining),
                channel_tenant_id=channel_tenant_id,
            )
            logger.info(
                "Debt partial payment: trader=%s customer=%s paid=%d remaining=%d",
                trader_phone, customer_name, amount, remaining,
            )
        else:
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.debt_settled.{message_id}",
                text=wa.debt_settled(display_name, debt_amount),
                channel_tenant_id=channel_tenant_id,
            )
            logger.info("Debt settled: trader=%s customer=%s amount=%d", trader_phone, customer_name, debt_amount)

    async def _do_list_debts(
        self,
        *,
        trader_phone: str,
        message_id: str,
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        """List all active debts for the trader as an interactive picker."""
        from app.modules.credit_sales.models import CreditSale, CreditSaleStatus
        from sqlalchemy import select
        from datetime import datetime, timezone as tz

        now = datetime.now(tz=tz.utc)

        async with async_session_factory() as session:
            result = await session.execute(
                select(CreditSale).where(
                    CreditSale.tenant_id == tenant_id,
                    CreditSale.status == CreditSaleStatus.ACTIVE,
                ).order_by(CreditSale.created_at.desc())
            )
            debts = list(result.scalars().all())

        if not debts:
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.debt_list.{message_id}",
                text=wa.debt_list_empty(),
                channel_tenant_id=channel_tenant_id,
            )
            return

        debt_list_data = []
        for d in debts:
            days_ago = max(1, int((now - d.created_at).total_seconds() / 86400)) if d.created_at else 0
            debt_list_data.append({
                "id": d.id,
                "name": d.customer_name,
                "amount": int(d.amount),
                "days_ago": days_ago,
            })
        total = sum(d["amount"] for d in debt_list_data)

        body, btn, sections = wa.debt_list_picker(debt_list_data, total)
        await self._reply_list(
            phone=trader_phone,
            tenant_id=tenant_id,
            event_id=f"trader.debt_list.{message_id}",
            body_text=body,
            button_label=btn,
            sections=sections,
            channel_tenant_id=channel_tenant_id,
        )

    async def _handle_debt_action(
        self,
        *,
        credit_sale_id: str,
        trader_phone: str,
        message_id: str,
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        """Show Settled/Remind buttons for a specific debt."""
        from app.modules.credit_sales.models import CreditSale, CreditSaleStatus
        from datetime import datetime, timezone as tz

        now = datetime.now(tz=tz.utc)
        async with async_session_factory() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(CreditSale).where(
                    CreditSale.id == credit_sale_id,
                    CreditSale.tenant_id == tenant_id,
                )
            )
            cs = result.scalar_one_or_none()

        if not cs or cs.status != CreditSaleStatus.ACTIVE:
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.debtact_notfound.{message_id}",
                text="This debt has already been settled or could not be found.",
                channel_tenant_id=channel_tenant_id,
            )
            return

        days_ago = max(1, int((now - cs.created_at).total_seconds() / 86400)) if cs.created_at else 0
        body, buttons = wa.debt_action_buttons(
            cs.customer_name, int(cs.amount), days_ago, cs.id,
        )
        await self._reply_interactive(
            phone=trader_phone,
            tenant_id=tenant_id,
            event_id=f"trader.debtact.{message_id}",
            body_text=body,
            buttons=buttons,
            channel_tenant_id=channel_tenant_id,
        )

    async def _handle_debt_settle(
        self,
        *,
        credit_sale_id: str,
        trader_phone: str,
        message_id: str,
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        """Settle a debt from a button tap."""
        from app.modules.credit_sales.models import CreditSale, CreditSaleStatus
        from app.infra.event_bus import Event, publish_event

        async with async_session_factory.begin() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(CreditSale).where(
                    CreditSale.id == credit_sale_id,
                    CreditSale.tenant_id == tenant_id,
                )
            )
            cs = result.scalar_one_or_none()
            if not cs or cs.status != CreditSaleStatus.ACTIVE:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"trader.settle_notfound.{message_id}",
                    text="This debt has already been settled or could not be found.",
                    channel_tenant_id=channel_tenant_id,
                )
                return
            customer_name = cs.customer_name
            amount = int(cs.amount)
            cs.status = CreditSaleStatus.SETTLED

        # Emit event so linked order auto-completes
        await publish_event(Event(
            event_name="credit_sale.status_changed",
            tenant_id=tenant_id,
            payload={
                "credit_sale_id": credit_sale_id,
                "order_id": cs.order_id,
                "new_status": "settled",
            },
        ))

        await self._reply(
            phone=trader_phone,
            tenant_id=tenant_id,
            event_id=f"trader.debt_settled.{message_id}",
            text=wa.debt_settled(customer_name, amount),
            channel_tenant_id=channel_tenant_id,
        )
        logger.info("Debt settled via button: credit_sale=%s customer=%s", credit_sale_id, customer_name)

    async def _handle_debt_remind(
        self,
        *,
        credit_sale_id: str,
        trader_phone: str,
        message_id: str,
        tenant_id: str,
        channel_tenant_id: str | None = None,
    ) -> None:
        """Send a manual reminder for a debt from a button tap."""
        from app.modules.credit_sales.service import CreditSaleService

        try:
            async with async_session_factory.begin() as session:
                svc = CreditSaleService(session)
                result = await svc.send_reminder(credit_sale_id, tenant_id=tenant_id)
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.debt_remind.{message_id}",
                text=wa.debt_remind_sent(result.message_sent.split(",")[0] if "," in result.message_sent else "the customer"),
                channel_tenant_id=channel_tenant_id,
            )
        except ValueError:
            # No conversation or max reminders reached
            async with async_session_factory() as session:
                from app.modules.credit_sales.models import CreditSale
                from sqlalchemy import select
                cs_result = await session.execute(
                    select(CreditSale).where(CreditSale.id == credit_sale_id)
                )
                cs = cs_result.scalar_one_or_none()
            name = cs.customer_name if cs else "this customer"
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.debt_remind_fail.{message_id}",
                text=wa.debt_remind_failed(name),
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

        # For credit orders, fetch outstanding balance from credit_sales
        credit_order_ids = [o.id for o in orders if o.is_credit]
        outstanding_map: dict[str, int] = {}
        if credit_order_ids:
            from app.modules.credit_sales.models import CreditSale, CreditSaleStatus
            async with async_session_factory() as cs_sess:
                cs_result = await cs_sess.execute(
                    select(CreditSale.order_id, CreditSale.amount).where(
                        CreditSale.order_id.in_(credit_order_ids),
                        CreditSale.status == CreditSaleStatus.ACTIVE,
                    )
                )
                for row in cs_result.all():
                    outstanding_map[row.order_id] = int(row.amount)

        order_data = []
        for o in orders:
            amount = outstanding_map.get(o.id, int(o.amount or 0)) if o.is_credit else int(o.amount or 0)
            order_data.append({
                "ref": o.id[:8],
                "customer_phone": o.customer_phone or "",
                "customer_name": o.customer_name or "",
                "amount": amount,
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
        customer_name: str | None = None,
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
            customer_name=customer_name,
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
        customer_name: str | None = None,
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
            customer_name=customer_name,
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

        # ── Handle product photo tap (PHOT_*) ────────────────────────────────
        if stripped.startswith("PHOT_"):
            # Route to the photo product session handler
            tsession_check = await get_trader_session(trader_phone)
            if tsession_check and tsession_check.get("state") == TRADER_AWAITING_PHOTO_PRODUCT:
                handled = await self._handle_trader_session(
                    tsession=tsession_check,
                    trader_phone=trader_phone,
                    message=message,
                    message_id=message_id,
                    trader=trader,
                    tenant_id=tenant_id,
                    channel_tenant_id=channel_tenant_id,
                )
                if handled:
                    return

        # ── Handle payment receipt taps (PAYRCVD *, PAYNOTRCVD *) ────────
        if stripped.startswith("PAYRCVD ") or stripped.startswith("PAYNOTRCVD "):
            is_received = stripped.startswith("PAYRCVD ")
            ref = message.strip().split(" ", 1)[1].strip().lower() if " " in message else ""
            if ref:
                order = await self._repo.get_by_ref_prefix(ref_prefix=ref)
                if order and order.state == OrderState.CONFIRMED:
                    customer_phone = order.customer_phone or ""
                    order_ref = order.id[:8]
                    if is_received:
                        # Mark order as PAID
                        try:
                            await self._transition(order, OrderState.PAID)
                            await self._db.commit()
                        except ConflictError as exc:
                            await self._reply(
                                phone=trader_phone,
                                tenant_id=tenant_id,
                                event_id=f"order.payrcvd_err.{message_id}",
                                text=f"Cannot mark order {order_ref} as paid: {exc}",
                                channel_tenant_id=channel_tenant_id,
                            )
                            return
                        await self._reply(
                            phone=trader_phone,
                            tenant_id=tenant_id,
                            event_id=f"order.payrcvd_trader.{order.id}",
                            text=wa.order_paid_to_trader(order_ref, customer_name=order.customer_name),
                            channel_tenant_id=channel_tenant_id,
                        )
                        if customer_phone:
                            await self._reply(
                                phone=customer_phone,
                                tenant_id=tenant_id,
                                event_id=f"order.payrcvd_customer.{order.id}",
                                text=wa.payment_confirmed_to_customer(trader_name, order_ref),
                                channel_tenant_id=channel_tenant_id,
                            )
                        logger.info("Trader confirmed payment order_id=%s", order.id)
                    else:
                        # Payment not received
                        if customer_phone:
                            await self._reply(
                                phone=customer_phone,
                                tenant_id=tenant_id,
                                event_id=f"order.paynotrcvd_customer.{order.id}",
                                text=wa.payment_not_received_to_customer(trader_name, order_ref),
                                channel_tenant_id=channel_tenant_id,
                            )
                        await self._reply(
                            phone=trader_phone,
                            tenant_id=tenant_id,
                            event_id=f"order.paynotrcvd_trader.{order.id}",
                            text=f"Noted. Customer has been notified that payment for order {order_ref} was not received.",
                            channel_tenant_id=channel_tenant_id,
                        )
                        logger.info("Trader rejected payment claim order_id=%s", order.id)
                else:
                    await self._reply(
                        phone=trader_phone,
                        tenant_id=tenant_id,
                        event_id=f"order.payrcvd_notfound.{message_id}",
                        text=wa.order_not_found_to_trader(ref),
                        channel_tenant_id=channel_tenant_id,
                    )
            return

        # ── Handle credit payment taps (CREDITPAID *, CREDITPART *) ──────
        if stripped.startswith("CREDITPAID ") or stripped.startswith("CREDITPART "):
            is_full = stripped.startswith("CREDITPAID ")
            ref = message.strip().split(" ", 1)[1].strip().lower() if " " in message else ""
            if ref:
                order = await self._repo.get_by_ref_prefix(ref_prefix=ref)
                if order and order.state == OrderState.CONFIRMED and order.is_credit:
                    order_ref = order.id[:8]
                    # Get actual outstanding from credit_sale
                    from app.modules.credit_sales.models import CreditSale as _CS, CreditSaleStatus as _CSS
                    async with async_session_factory() as _cs_sess:
                        _cs_r = await _cs_sess.execute(
                            select(_CS.amount).where(_CS.order_id == order.id, _CS.status == _CSS.ACTIVE)
                        )
                        _cs_row = _cs_r.scalar_one_or_none()
                    total = int(_cs_row) if _cs_row else int(order.amount or 0)
                    if is_full:
                        # Paid in full: order → PAID + settle linked credit sale
                        try:
                            await self._transition(order, OrderState.PAID)
                            await self._db.commit()
                        except ConflictError as exc:
                            await self._reply(
                                phone=trader_phone, tenant_id=tenant_id,
                                event_id=f"order.creditpaid_err.{message_id}",
                                text=f"Cannot mark order {order_ref} as paid: {exc}",
                                channel_tenant_id=channel_tenant_id,
                            )
                            return
                        # Settle the linked credit sale
                        from app.modules.credit_sales.models import CreditSale, CreditSaleStatus
                        async with async_session_factory.begin() as cs_session:
                            from sqlalchemy import select, update
                            await cs_session.execute(
                                update(CreditSale)
                                .where(CreditSale.order_id == order.id, CreditSale.status == CreditSaleStatus.ACTIVE)
                                .values(status=CreditSaleStatus.SETTLED)
                            )
                        await self._reply(
                            phone=trader_phone, tenant_id=tenant_id,
                            event_id=f"order.creditpaid_trader.{order.id}",
                            text=wa.credit_paid_in_full(order_ref, total, customer_name=order.customer_name),
                            channel_tenant_id=channel_tenant_id,
                        )
                        # Notify customer
                        customer_phone = order.customer_phone or ""
                        if customer_phone:
                            await self._reply(
                                phone=customer_phone, tenant_id=tenant_id,
                                event_id=f"order.creditpaid_customer.{order.id}",
                                text=wa.payment_confirmed_to_customer(trader_name, order_ref),
                                channel_tenant_id=channel_tenant_id,
                            )
                        logger.info("Credit order paid in full order_id=%s", order.id)
                    else:
                        # Partial payment: ask for amount
                        from app.modules.orders.session import set_trader_session, TRADER_AWAITING_CREDIT_PARTIAL
                        await set_trader_session(trader_phone, {
                            "state": TRADER_AWAITING_CREDIT_PARTIAL,
                            "order_id": order.id,
                            "order_ref": order_ref,
                            "customer_name": order.customer_name or "",
                        })
                        await self._reply(
                            phone=trader_phone, tenant_id=tenant_id,
                            event_id=f"order.creditpart_prompt.{message_id}",
                            text=wa.credit_partial_prompt(order_ref, total, customer_name=order.customer_name),
                            channel_tenant_id=channel_tenant_id,
                        )
                else:
                    await self._reply(
                        phone=trader_phone, tenant_id=tenant_id,
                        event_id=f"order.creditpaid_notfound.{message_id}",
                        text=wa.order_not_found_to_trader(ref),
                        channel_tenant_id=channel_tenant_id,
                    )
            return

        # ── Handle negotiation response taps (NEGACCEPT_*, NEGCOUNTER_*, NEGDECLINE_*) ──
        if stripped.startswith("NEGACCEPT_") or stripped.startswith("NEGDECLINE_"):
            customer_phone_from_tap = message.strip().split("_", 1)[1] if "_" in message else ""
            is_accept = stripped.startswith("NEGACCEPT_")
            await self._handle_negotiation_response(
                is_accept=is_accept,
                customer_phone=customer_phone_from_tap,
                trader_phone=trader_phone,
                trader=trader,
                message_id=message_id,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
            return

        if stripped.startswith("NEGCOUNTER_"):
            from app.modules.orders.session import (
                set_trader_session,
                get_pending_negotiation,
                TRADER_AWAITING_COUNTER_PRICE,
            )
            customer_phone_from_tap = message.strip().split("_", 1)[1] if "_" in message else ""
            # Look up the pending negotiation for context
            neg = await get_pending_negotiation(trader_phone, customer_phone_from_tap)
            original_price = neg.get("original_price", 0) if neg else 0
            offered_price = neg.get("offered_price", 0) if neg else 0

            await set_trader_session(trader_phone, {
                "state": TRADER_AWAITING_COUNTER_PRICE,
                "customer_phone": customer_phone_from_tap,
            })
            await self._reply(
                phone=trader_phone,
                tenant_id=tenant_id,
                event_id=f"trader.neg_counter_prompt.{message_id}",
                text=wa.negotiation_counter_prompt(original_price, offered_price),
                channel_tenant_id=channel_tenant_id,
            )
            return

        # ── Handle debt action taps (DEBTACT_*, SETTLE_*, REMIND_*) ──────
        if stripped.startswith("DEBTACT_"):
            credit_sale_id = message.strip()[8:]
            await self._handle_debt_action(
                credit_sale_id=credit_sale_id,
                trader_phone=trader_phone,
                message_id=message_id,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
            return

        if stripped.startswith("SETTLE_"):
            credit_sale_id = message.strip()[7:]
            await self._handle_debt_settle(
                credit_sale_id=credit_sale_id,
                trader_phone=trader_phone,
                message_id=message_id,
                tenant_id=tenant_id,
                channel_tenant_id=channel_tenant_id,
            )
            return

        if stripped.startswith("REMIND_"):
            credit_sale_id = message.strip()[7:]
            await self._handle_debt_remind(
                credit_sale_id=credit_sale_id,
                trader_phone=trader_phone,
                message_id=message_id,
                tenant_id=tenant_id,
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
            # For credit orders, show outstanding balance instead of original amount
            if order.is_credit:
                from app.modules.credit_sales.models import CreditSale as _OrdCS, CreditSaleStatus as _OrdCSS
                async with async_session_factory() as _ord_cs_sess:
                    _ord_cs_r = await _ord_cs_sess.execute(
                        select(_OrdCS.amount).where(_OrdCS.order_id == order.id, _OrdCS.status == _OrdCSS.ACTIVE)
                    )
                    _ord_cs_amt = _ord_cs_r.scalar_one_or_none()
                if _ord_cs_amt is not None:
                    total = int(_ord_cs_amt)
            cust_phone = order.customer_phone or "unknown"
            cust_display = order.customer_name or (f"+{cust_phone}" if cust_phone != "unknown" else "Unknown")
            ref_lower = order_ref.lower()
            # Show context-appropriate buttons based on order state
            if order.state == OrderState.INQUIRY:
                body, buttons = wa.order_action_buttons(
                    ref_lower, cust_display, total, order.state, order.is_credit
                )
                await self._reply_interactive(
                    phone=trader_phone, tenant_id=tenant_id,
                    event_id=f"trader.ordact.{message_id}",
                    body_text=body, buttons=buttons,
                    channel_tenant_id=channel_tenant_id,
                )
            elif order.state == OrderState.CONFIRMED:
                body, buttons = wa.pending_order_actions(
                    ref_lower, cust_display, total, is_credit=order.is_credit,
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

        if result.intent == TRADER_BANK:
            from app.modules.orders.session import set_trader_session, TRADER_AWAITING_BANK_DETAILS
            bank_name = trader.get("bank_name", "")
            if bank_name:
                await self._reply(
                    phone=trader_phone, tenant_id=tenant_id,
                    event_id=f"trader.bank_current.{message_id}",
                    text=wa.bank_details_current(
                        bank_name, trader.get("bank_account_number", ""),
                        trader.get("bank_account_name", ""),
                    ),
                    channel_tenant_id=channel_tenant_id,
                )
            else:
                await self._reply(
                    phone=trader_phone, tenant_id=tenant_id,
                    event_id=f"trader.bank_prompt.{message_id}",
                    text=wa.bank_details_not_set(),
                    channel_tenant_id=channel_tenant_id,
                )
            await set_trader_session(trader_phone, {"state": TRADER_AWAITING_BANK_DETAILS})
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
            TRADER_CONFIRM, TRADER_CANCEL, TRADER_PAID, TRADER_CREDIT
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

            # Trader sent a photo outside any session → product photo upload
            if image_bytes:
                await self._handle_trader_product_photo(
                    trader_phone=trader_phone,
                    message=message,
                    message_id=message_id,
                    image_bytes=image_bytes,
                    trader=trader,
                    tenant_id=tenant_id,
                    channel_tenant_id=channel_tenant_id,
                )
                return

            # Only show menu if the message looks like a command attempt.
            # Random personal messages (e.g. "pick up the kids") → stay silent.
            import re as _cmd_re
            _COMMAND_HINT = _cmd_re.compile(
                r"\b(menu|help|order|add|remove|price|catalogue|catalog|"
                r"debt|paid|bank|credit|who owes|pricelist|category|store|commands)\b",
                _cmd_re.IGNORECASE,
            )
            if _COMMAND_HINT.search(message):
                await self._send_trader_menu(
                    trader_phone=trader_phone,
                    message_id=message_id,
                    tenant_id=tenant_id,
                    channel_tenant_id=channel_tenant_id,
                )
            # Otherwise: stay silent — likely a personal message sent to wrong number
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
        cust_name: str | None = order.customer_name or None

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
            body_text, buttons = wa.order_confirmed_to_trader(ref, customer_name=cust_name, customer_phone=customer_phone)
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
                bank_name = trader.get("bank_name", "")
                bank_acct = trader.get("bank_account_number", "")
                bank_acct_name = trader.get("bank_account_name", "")

                if bank_name and bank_acct:
                    # Send bank details to customer for payment
                    await self._reply(
                        phone=customer_phone,
                        tenant_id=tenant_id,
                        event_id=f"order.confirmed_customer.{order.id}",
                        text=wa.payment_details_to_customer(
                            trader_name, total, bank_name, bank_acct,
                            bank_acct_name, ref,
                        ),
                        channel_tenant_id=channel_tenant_id,
                    )
                else:
                    # No bank details — send regular confirmation
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
                text=wa.order_cancelled_to_trader(ref, customer_name=cust_name),
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
                text=wa.order_paid_to_trader(ref, customer_name=cust_name),
                channel_tenant_id=channel_tenant_id,
            )
            logger.info("Trader marked order PAID order_id=%s ref=%s", order.id, ref)

        elif result.intent == TRADER_CREDIT:
            # Create a credit sale linked to this order
            from decimal import Decimal as D
            from app.modules.credit_sales.models import CreditSale

            # Guard: check if credit sale already exists for this order
            if order.is_credit:
                await self._reply(
                    phone=trader_phone,
                    tenant_id=tenant_id,
                    event_id=f"order.credit_dup.{message_id}",
                    text=wa.order_already_on_credit(ref, customer_name=cust_name),
                    channel_tenant_id=channel_tenant_id,
                )
                return

            total = int(order.amount or 0)
            cust_phone = order.customer_phone or "unknown"
            cust_name = order.customer_name or (f"+{cust_phone}" if cust_phone != "unknown" else "Unknown")

            try:
                async with async_session_factory.begin() as cs_session:
                    credit_sale = CreditSale(
                        tenant_id=order.tenant_id,
                        order_id=order.id,
                        conversation_id=order.conversation_id,
                        customer_name=cust_name,
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
                text=wa.order_credit_to_trader(ref, cust_name, total),
                channel_tenant_id=channel_tenant_id,
            )
            logger.info("Trader marked order CREDIT order_id=%s ref=%s", order.id, ref)


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
                customer_name=order.customer_name,
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
