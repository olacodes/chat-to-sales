"""
app/modules/payments/router.py

Routes
------
POST /payments/          – Initiate a payment for a CONFIRMED order
GET  /payments/{id}      – Fetch a payment by ID
POST /payments/webhook   – Paystack webhook callback (signature-verified)

Paystack Webhook Signature
--------------------------
Paystack signs every webhook POST body with HMAC-SHA512 using your secret key
and includes the hex digest in the `x-paystack-signature` header.

If PAYSTACK_SECRET_KEY is set the router enforces the check (production).
If it is an empty string (local dev) the check is skipped so you can test
with plain curl / mock webhooks without a real Paystack account.
"""

import hashlib
import hmac
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from app.core.config import Settings, get_settings
from app.core.dependencies import DBSessionDep
from app.core.exceptions import InvalidWebhookSignatureError
from app.core.logging import get_logger
from app.modules.payments.models import PaymentStatus
from app.modules.payments.schemas import (
    PaymentInitiateRequest,
    PaymentListResponse,
    PaymentOut,
)
from app.modules.payments.service import PaymentService

logger = get_logger(__name__)
router = APIRouter(prefix="/payments", tags=["Payments"])


# ── Dependency ────────────────────────────────────────────────────────────────


def _service(db: DBSessionDep) -> PaymentService:
    return PaymentService(db)


ServiceDep = Annotated[PaymentService, Depends(_service)]


# ── Signature helper ──────────────────────────────────────────────────────────


def _verify_paystack_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """
    Verify a Paystack webhook using HMAC-SHA512.

    Paystack computes: HMAC-SHA512(secret_key, raw_request_body)
    and sends the hex digest in the x-paystack-signature header.
    """
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("")
async def list_payments(
    tenant_id: str,
    svc: ServiceDep,
    status: PaymentStatus | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PaymentListResponse:
    return await svc.list_payments(
        tenant_id=tenant_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.post("/", status_code=201)
async def initiate_payment(
    body: PaymentInitiateRequest,
    svc: ServiceDep,
) -> PaymentOut:
    """
    Create a PENDING payment for a CONFIRMED order.

    Returns a `payment_link` the customer should be redirected to.
    The order must be in CONFIRMED state and have at least one item (amount > 0).
    """
    return await svc.create_payment_for_order(
        order_id=body.order_id,
        tenant_id=body.tenant_id,
    )


@router.get("/{payment_id}")
async def get_payment(payment_id: str, svc: ServiceDep) -> PaymentOut:
    return await svc.get_by_id(payment_id)


@router.post("/webhook", status_code=200)
async def paystack_webhook(
    request: Request,
    svc: ServiceDep,
    settings: Annotated[Settings, Depends(get_settings)],
    x_paystack_signature: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    """
    Receive a Paystack payment webhook.

    Paystack sends `charge.success` on payment confirmation.
    The handler is idempotent — repeated deliveries of the same reference
    are safely ignored after the first successful processing.
    """
    raw_body = await request.body()
    logger.info("Paystack webhook received bytes=%d", len(raw_body))

    # ── Signature verification ────────────────────────────────────────────────
    if settings.PAYSTACK_SECRET_KEY:
        if not x_paystack_signature:
            logger.warning("Paystack webhook: missing x-paystack-signature header")
            raise InvalidWebhookSignatureError()
        if not _verify_paystack_signature(
            raw_body, x_paystack_signature, settings.PAYSTACK_SECRET_KEY
        ):
            logger.warning("Paystack webhook: signature mismatch")
            raise InvalidWebhookSignatureError()

    # ── Parse body ────────────────────────────────────────────────────────────
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON in webhook body.",
        )

    event_name: str = payload.get("event", "")
    data: dict = payload.get("data", {})
    reference: str = data.get("reference", "")
    success: bool = event_name == "charge.success"

    logger.info(
        "Paystack webhook event=%s reference=%s success=%s",
        event_name,
        reference,
        success,
    )

    if not reference:
        logger.warning("Paystack webhook: missing reference in data — ignoring")
        return {"status": "ignored"}

    await svc.handle_webhook(reference=reference, success=success)
    return {"status": "received"}
