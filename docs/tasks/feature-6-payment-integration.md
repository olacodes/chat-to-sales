# Feature 6: Payment Integration — Task Tracker

## Overview

Paystack-powered payment links sent to customers after order confirmation. Traders on Oja and Alatise tiers get auto-generated payment links. ChatToSales never holds money — Paystack pays directly to the trader's bank account.

## Done

| # | Task | Description |
|---|------|-------------|
| ✅ | Payment database model | Payment entity: order_id (FK), reference (unique), amount, currency (NGN), status (PENDING/SUCCESS/FAILED), provider (paystack), payment_link. Three indexes + unique constraint on reference. |
| ✅ | Payment repository | Async CRUD: get_by_id, get_by_reference, get_active_for_order, create_payment, update_status. List with pagination + tenant-scoped filtering. |
| ✅ | Payment service | create_payment_for_order: validates order state (CONFIRMED), checks amount > 0, prevents duplicate payments. handle_webhook: idempotent via reference, emits `payment.confirmed` event. Reference format: `pay_{uuid4}`. |
| ✅ | REST API endpoints | `POST /payments/` (initiate), `GET /payments/{id}`, `GET /payments/` (list + filter), `POST /payments/webhook` (Paystack receiver). |
| ✅ | Webhook security | HMAC-SHA512 signature verification of `x-paystack-signature` header. Skipped in dev (no key), enforced in prod. |
| ✅ | Order transition handler | Listens for `payment.confirmed` events → transitions order CONFIRMED → PAID. Idempotent, async background task. |
| ✅ | Customer notification | On payment.confirmed → sends WhatsApp message: "Payment successful! Thank you for your purchase." Via conversation lookup. |
| ✅ | Pydantic schemas | PaymentInitiateRequest, PaymentOut, PaymentListItem, PaymentListResponse, PaystackWebhookPayload. |
| ✅ | Configuration | PAYSTACK_SECRET_KEY env var. Validated in production mode. |
| ✅ | Module registration | Router + event handlers registered in main.py lifespan. |

## Not Done (MVP)

| # | Task | Description | Priority |
|---|------|-------------|----------|
| ⬜ | Real Paystack API integration | Replace mock payment link (`paystack.mock/pay/...`) with actual `POST https://api.paystack.co/transaction/initialize`. Extract `authorization_url` from response. Handle API errors. | High |
| ⬜ | Customer email capture | Paystack requires customer email. Options: ask during order flow, use phone-based email (`2348...@wa.chattosales.com`), or add email field to order. | High |
| ⬜ | WhatsApp payment link delivery | Send payment link to customer via WhatsApp after order confirmation. Interactive button message: "Pay N85,000 for your order" [Pay Now]. | High |
| ⬜ | Trader-initiated payment link | From dashboard or WhatsApp, trader sends a payment link to customer for a confirmed order. `PAY <ref>` command or button on order detail. | High |
| ⬜ | Payment status on dashboard | Show payment status (pending/success/failed) on the orders page. Badge or icon next to each order. | Medium |
| ⬜ | Failed payment handling | When Paystack webhook reports failure: update Payment status to FAILED, notify customer ("Payment didn't go through. Please try again."), allow retry. | Medium |

## Nice to Have (Post-MVP)

| # | Task | Description |
|---|------|-------------|
| ⬜ | Automatic payment link on confirm | When trader confirms an order, auto-generate and send payment link if they're on Oja/Alatise tier. Zero trader effort. |
| ⬜ | Payment retry | Customer can request a new payment link if the first one expired or failed. `PAY AGAIN` or re-tap button. |
| ⬜ | Refund integration | `POST https://api.paystack.co/refund` when order is cancelled after payment. Track refund status. |
| ⬜ | Tier enforcement | Only Oja (N1,500/mo) and Alatise (N3,500/mo) tiers can generate payment links. Ofe (free) tier: manual payment only. |
| ⬜ | Payment receipt | After successful payment, send formatted WhatsApp receipt: order details, amount, payment reference, date. |
| ⬜ | Split payment | Support partial payments via Paystack (customer pays part, owes rest → auto-creates credit sale for remainder). |
| ⬜ | Payment analytics | Dashboard: total collected, payment success rate, average time to pay, failed payment count. |
| ⬜ | Reconciliation | Track Paystack settlement status to trader's bank account. Show "Settled" vs "Processing" on dashboard. |
| ⬜ | Multiple payment providers | Abstract payment provider interface so other gateways (Flutterwave, Monnify) can be added alongside Paystack. |
| ⬜ | Payment reminders | If payment link sent but not paid within X hours, send a gentle reminder: "Your payment link for order {ref} is still open." |
| ⬜ | QR code payment | Generate QR code for the payment link that customer can scan in-store. |

## Key Files

| File | Purpose |
|------|---------|
| `app/modules/payments/models.py` | Payment entity + PaymentStatus enum |
| `app/modules/payments/repository.py` | Database queries (CRUD + list + status updates) |
| `app/modules/payments/service.py` | Business logic: create payment, handle webhook, mock link generation |
| `app/modules/payments/router.py` | REST API endpoints + Paystack webhook receiver |
| `app/modules/payments/handlers.py` | Event listener: payment.confirmed → order CONFIRMED → PAID |
| `app/modules/payments/schemas.py` | Pydantic request/response models |
| `app/modules/notifications/handlers.py` | Payment notification handler (WhatsApp confirmation to customer) |
| `app/modules/orders/service.py` | `handle_payment_confirmed()` method |
| `app/core/config.py` | PAYSTACK_SECRET_KEY configuration |
| `alembic/versions/000_initial_schema.py` | Payment table in initial migration |

## Architecture Notes

### Payment flow (when complete)
```
Trader confirms order
    ↓
POST /payments/ (or auto-trigger for Oja/Alatise tier)
    ↓
Paystack API: POST /transaction/initialize
    → returns authorization_url (payment link)
    ↓
Payment record created (PENDING)
    ↓
Payment link sent to customer via WhatsApp: "Pay N85,000" [Pay Now]
    ↓
Customer taps link → Paystack checkout page → pays
    ↓
Paystack webhook: POST /payments/webhook (charge.success)
    ↓
Payment status: PENDING → SUCCESS
    ↓
Event: payment.confirmed
    ↓
Order: CONFIRMED → PAID
    ↓
Customer notified: "Payment successful!"
Trader notified: "Payment received for order {ref}."
```

### Design rules
- ChatToSales never holds money — Paystack pays directly to trader's bank
- Payment links expire after 24 hours (Paystack default)
- One active payment per order (prevent duplicate charges)
- Webhook is idempotent — safe to receive the same event multiple times
- Signature verification mandatory in production
