# Feature 6: Payment Integration — Task Tracker

## Overview

Two-tier payment system: (1) Bank details sharing for all traders — auto-sends bank account info to customers after order confirmation, zero friction. (2) Paystack payment links as optional premium upgrade for Oja/Alatise tiers. ChatToSales never holds money.

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
| ✅ | Trader bank details storage | Migration 026: bank_name, bank_account_number, bank_account_name on Trader model. Repository: update_bank_details(). |
| ✅ | BANK WhatsApp command | `BANK` or menu → Bank Details: shows current bank info or prompts setup. Trader types "GTBank 0123456789" → saved. TRADER_AWAITING_BANK_DETAILS session state. |
| ✅ | Auto-send bank details on confirm | When trader confirms an order and has bank details set, customer receives: bank name, account number, account name, total, and "send your receipt or type PAID". Falls back to regular confirmation if no bank details. |
| ✅ | Bank details menu item | "Bank Details" in the Store section of the trader menu. |
| ✅ | Bank details in trader cache | bank_name, bank_account_number, bank_account_name included in trader dict and Redis cache. |

| ✅ | Customer payment receipt detection | Customer types "paid"/"sent"/"transferred" or sends payment screenshot → finds most recent CONFIRMED order → notifies trader with [Payment Received] / [Not Received] buttons → PAYRCVD marks order PAID, PAYNOTRCVD notifies customer. NLP Layer 1 regex + smart parser both detect PAYMENT_SENT intent. Payment screenshots detected when customer has a confirmed order and sends an image. Quiet mode allows payment through. |

## Not Done (MVP)

| # | Task | Description | Priority |
|---|------|-------------|----------|
| ✅ | Bank account name verification | Paystack `GET /bank/resolve` verifies account name. Bank name mapped to bank_code via 30+ Nigerian bank lookup table. Resolved name shown to trader with [Yes, save it] / [No, re-enter] buttons. Fallback to business name if Paystack key not set or resolve fails. Unknown bank names rejected with prompt. New file: `app/infra/paystack.py`. New session state: TRADER_AWAITING_BANK_CONFIRM. |
| ✅ | Payment status on dashboard | Orders page shows "Awaiting Payment" outline badge on confirmed non-credit orders. Credit badge on credit orders. Status badges (Inquiry/Confirmed/Paid/Completed/Cancelled) already present. Clear payment flow visibility at a glance. | Medium |
| ⬜ | Paystack subaccount (premium tier) | For Oja/Alatise traders who opt in: create Paystack subaccount with trader's bank details, send payment links alongside bank details. Auto-confirm via webhook. | Medium |
| ⬜ | Real Paystack API integration | Replace mock payment link with actual `POST https://api.paystack.co/transaction/initialize` + subaccount. For premium tiers only. | Medium |
| ⬜ | WhatsApp payment link delivery | Send Paystack payment link alongside bank details: "Pay to bank OR [Pay Online]". For premium tiers only. | Medium |

## Nice to Have (Post-MVP)

| # | Task | Description |
|---|------|-------------|
| ⬜ | Automatic payment link on confirm | For premium tiers: auto-generate Paystack link + bank details when trader confirms. Zero trader effort. |
| ⬜ | Payment retry | Customer can request a new payment link if the first one expired or failed. |
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

### Payment flow — Bank details (MVP, all tiers)
```
Trader sets bank details once: BANK → "GTBank 0123456789"
    ↓
Customer places order → Trader taps Confirm
    ↓
Customer gets: "Order confirmed! Total: N85,000
  Pay to: GTBank / 0123456789 / Mama Caro Provisions
  Send your receipt or type PAID."
    ↓
Customer transfers via mobile banking → sends receipt
    ↓
Trader verifies → taps "Payment Received" or types PAID <ref>
    ↓
Order: CONFIRMED → PAID
```

### Payment flow — Paystack (premium, Oja/Alatise tiers)
```
Trader confirms order
    ↓
POST /payments/ (auto-trigger for premium tiers)
    ↓
Paystack API: POST /transaction/initialize (with subaccount)
    → returns authorization_url (payment link)
    ↓
Customer gets: bank details + "Or pay online: [Pay Now]"
    ↓
Customer taps link → Paystack checkout → pays
    ↓
Paystack webhook: POST /payments/webhook (charge.success)
    ↓
Order: CONFIRMED → PAID (automatic, no trader verification needed)
```

### Design rules
- ChatToSales never holds money — bank transfer goes direct, Paystack pays to subaccount
- Bank details sharing is the primary payment method (zero trust issues)
- Paystack is an optional premium upgrade (auto-confirmation + card payments)
- Payment links expire after 24 hours (Paystack default)
- One active payment per order (prevent duplicate charges)
- Webhook is idempotent — safe to receive the same event multiple times
- Signature verification mandatory in production
