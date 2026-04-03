"""
app/modules/payments/service.py

PaymentService — orchestrates payment creation and webhook processing.

Design
------
- create_payment_for_order()  HTTP path: validates order state, generates a
  Paystack checkout link (mocked for MVP), persists the Payment record,
  emits payment.created, and commits.

- handle_webhook()  HTTP path: verifies idempotency (reference uniqueness),
  updates payment status, emits payment.confirmed on success. The
  payment.confirmed event drives the order → PAID transition via the
  payments/handlers.py background listener — the webhook handler itself
  never directly touches the order.

Upgrading to real Paystack
--------------------------
Replace _generate_payment_link() with a real HTTP call:

    POST https://api.paystack.co/transaction/initialize
    Authorization: Bearer {PAYSTACK_SECRET_KEY}
    Body: { "email": <customer_email>, "amount": <kobo>, "reference": <ref> }
    → response["data"]["authorization_url"]
"""

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.infra.event_bus import Event, publish_event
from app.modules.orders.models import OrderState
from app.modules.orders.repository import OrderRepository
from app.modules.payments.models import Payment, PaymentStatus
from app.modules.payments.repository import PaymentRepository

logger = get_logger(__name__)

_EVT_PAYMENT_CREATED = "payment.created"
_EVT_PAYMENT_CONFIRMED = "payment.confirmed"
_MOCK_PAYMENT_BASE = "https://paystack.mock/pay"


class PaymentService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = PaymentRepository(db)
        self._order_repo = OrderRepository(db)

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _make_reference() -> str:
        """Generate a unique, URL-safe payment reference."""
        return f"pay_{uuid4().hex[:20]}"

    @staticmethod
    def _generate_payment_link(reference: str) -> str:
        """
        Return a checkout URL for the given reference.

        MVP: returns a mock URL.  For production swap with:
            POST https://api.paystack.co/transaction/initialize
            → response["data"]["authorization_url"]
        """
        return f"{_MOCK_PAYMENT_BASE}/{reference}"

    async def _get_payment_or_404(
        self, payment_id: str, tenant_id: str | None = None
    ) -> Payment:
        payment = await self._repo.get_by_id(payment_id=payment_id, tenant_id=tenant_id)
        if payment is None:
            raise NotFoundError("Payment", payment_id)
        return payment

    # ── Public API ────────────────────────────────────────────────────────────

    async def create_payment_for_order(
        self,
        order_id: str,
        tenant_id: str,
    ) -> Payment:
        """
        Initiate a payment for a CONFIRMED order and return a checkout link.

        Validations (raises ConflictError):
        - Order must be in CONFIRMED state.
        - Order must have an amount > 0 (add items first).
        - No PENDING or SUCCESS payment may already exist for this order.
        """
        order = await self._order_repo.get_by_id(order_id=order_id, tenant_id=tenant_id)
        if order is None:
            raise NotFoundError("Order", order_id)

        if order.state != OrderState.CONFIRMED:
            raise ConflictError(
                f"Cannot initiate payment for an order in '{order.state}' state. "
                "Confirm the order first."
            )

        if order.amount is None:
            raise ConflictError(
                "Cannot initiate payment: order has no amount. "
                "Add items to the order first."
            )

        existing = await self._repo.get_active_for_order(
            order_id=order_id, tenant_id=tenant_id
        )
        if existing is not None:
            raise ConflictError(
                f"An active payment already exists for this order "
                f"(reference={existing.reference}, status={existing.status})."
            )

        reference = self._make_reference()
        payment_link = self._generate_payment_link(reference)

        payment = await self._repo.create_payment(
            tenant_id=tenant_id,
            order_id=order_id,
            reference=reference,
            amount=order.amount,
            currency=order.currency,
            payment_link=payment_link,
        )

        await publish_event(
            Event(
                event_name=_EVT_PAYMENT_CREATED,
                tenant_id=tenant_id,
                payload={
                    "payment_id": payment.id,
                    "order_id": order_id,
                    "reference": reference,
                    "amount": str(order.amount),
                    "currency": order.currency,
                    "payment_link": payment_link,
                },
            )
        )
        logger.info(
            "Payment created payment_id=%s order=%s reference=%s",
            payment.id,
            order_id,
            reference,
        )
        await self._db.commit()
        return payment

    async def get_by_id(
        self, payment_id: str, *, tenant_id: str | None = None
    ) -> Payment:
        return await self._get_payment_or_404(payment_id, tenant_id)

    async def handle_webhook(self, reference: str, success: bool) -> Payment | None:
        """
        Process a Paystack webhook event.

        Idempotency guarantee: if the payment is already SUCCESS, the webhook
        is acknowledged and ignored — no duplicate state change or event.

        On success → status = SUCCESS, emit payment.confirmed.
        On failure → status = FAILED.

        The payment.confirmed event is consumed by payments/handlers.py, which
        transitions the order CONFIRMED → PAID in a separate transaction.
        """
        logger.info("Webhook processing reference=%s success=%s", reference, success)
        payment = await self._repo.get_by_reference(reference=reference)
        if payment is None:
            logger.warning(
                "Webhook references unknown payment reference=%s — ignoring",
                reference,
            )
            return None

        # ── Idempotency ───────────────────────────────────────────────────────
        if payment.status == PaymentStatus.SUCCESS:
            logger.info(
                "Payment already SUCCESS reference=%s — webhook ignored (idempotent)",
                reference,
            )
            return payment

        new_status = PaymentStatus.SUCCESS if success else PaymentStatus.FAILED
        await self._repo.update_status(payment=payment, status=new_status)
        logger.info(
            "Payment %s payment_id=%s reference=%s", new_status, payment.id, reference
        )

        if success:
            await publish_event(
                Event(
                    event_name=_EVT_PAYMENT_CONFIRMED,
                    tenant_id=payment.tenant_id,
                    payload={
                        "payment_id": payment.id,
                        "order_id": payment.order_id,
                        "reference": payment.reference,
                        "tenant_id": payment.tenant_id,
                        "amount": str(payment.amount),
                        "currency": payment.currency,
                    },
                )
            )
            logger.info(
                "payment.confirmed emitted payment_id=%s order_id=%s",
                payment.id,
                payment.order_id,
            )
        else:
            logger.info(
                "Payment FAILED reference=%s payment_id=%s", reference, payment.id
            )

        await self._db.commit()
        return payment
