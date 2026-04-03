# Scenario Testing Guide

End-to-end functional test scenarios for **ChatToSales** — an event-driven conversational
commerce backend. Each scenario is fully executable with `curl` and `psql` on a local
Docker stack.

---

## System Overview

ChatToSales converts unstructured customer messages (WhatsApp, SMS, web) into structured
commerce events. A customer sends a natural-language message; the system automatically
creates a conversation record, detects order intent, spins up an order, and processes
payment — all asynchronously through a Redis Pub/Sub event bus.

```
Inbound message
    │
    ▼
POST /webhooks/webhook
    │  publishes message.received
    ▼
Conversation Handler ──────────────── DB: conversations, messages
    │  publishes conversation.message_saved
    ▼
Order Intent Handler ───────────────── DB: orders (state = INQUIRY)
    │  emits order.created
    ▼
                    ── (operator) POST /orders/{id}/confirm ──▶ DB: state = CONFIRMED
                    ── (operator) POST /orders/{id}/items   ──▶ DB: order_items
                    ── (operator) POST /payments/           ──▶ DB: payments (PENDING)
                    │  emits payment.created
                    ▼
POST /payments/webhook  (Paystack callback)
    │  emits payment.confirmed
    ▼
Payment Confirmed Handler ─────────── DB: orders (state = PAID)
    │  emits order.state_changed, order.paid
    ▼
                    ── (operator) POST /orders/{id}/complete ──▶ DB: state = COMPLETED
```

---

## Prerequisites

### 1. Start the full stack

Always use a fresh volume so the schema is rebuilt cleanly:

```bash
docker compose down -v && docker compose up --build -d
```

### 2. Confirm all services are healthy

```bash
docker compose ps
```

All three services (`app`, `postgres`, `redis`) should show `healthy` or `running`.

### 3. Verify the API is up

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

Expected:

```json
{
  "status": "ok",
  "environment": "development",
  "version": "0.1.0"
}
```

### 4. Open a Redis event monitor (keep this open throughout all scenarios)

```bash
docker compose exec redis redis-cli PSUBSCRIBE "chattosales.events.tenant-abc-123.*"
```

Every event published during testing appears here in real time.

---

## Test Data

| Variable    | Value                          |
| ----------- | ------------------------------ |
| `TENANT_ID` | `tenant-abc-123`               |
| `SENDER`    | `+2348012345678`               |
| `BASE_URL`  | `http://localhost:8000/api/v1` |

Set these in your shell for copy-paste convenience:

```bash
TENANT_ID="tenant-abc-123"
SENDER="+2348012345678"
BASE_URL="http://localhost:8000/api/v1"
```

---

## Scenario 1 — Full Happy Path

> Customer sends a message → conversation stored → order created → confirmed →
> payment generated → webhook triggers → order marked PAID → completed.

---

### Step 1 — Send an inbound message

```bash
curl -s -X POST "$BASE_URL/webhooks/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "'"$TENANT_ID"'",
    "channel": "whatsapp",
    "sender": "'"$SENDER"'",
    "message": "Hello, I want to buy the blue sneakers",
    "message_id": "wamid.sc1-001"
  }' | python3 -m json.tool
```

**Expected HTTP response — 202 Accepted:**

```json
{
  "channel": "whatsapp",
  "sender": "+2348012345678",
  "message": "Hello, I want to buy the blue sneakers",
  "message_lower": "hello, i want to buy the blue sneakers",
  "word_count": 8,
  "tenant_id": "tenant-abc-123",
  "is_empty": false
}
```

**Expected Redis events (in the monitor terminal):**

```
message.received        ← published by ingestion service
conversation.message_saved  ← published by conversation handler after DB commit
order.created           ← published by order-intent handler (~1 s later)
```

Allow ~1 second for the two background handlers to process the event before
checking the database.

---

### Step 2 — Verify conversation and message in the database

```bash
# Conversation row
docker compose exec postgres \
  psql -U postgres -d chattosales -c \
  "SELECT id, phone_number, channel, status FROM conversations;"
```

Expected output:

```
 id (uuid)  | phone_number     | channel   | status
------------+------------------+-----------+--------
 <UUID>     | +2348012345678   | whatsapp  | active
```

```bash
# Message row — external_id matches the message_id we sent
docker compose exec postgres \
  psql -U postgres -d chattosales -c \
  "SELECT id, sender, content, external_id FROM messages;"
```

Expected:

```
 id (uuid) | sender          | content                              | external_id
-----------+-----------------+--------------------------------------+---------------
 <UUID>    | +2348012345678  | Hello, I want to buy the blue sneakers | wamid.sc1-001
```

---

### Step 3 — Verify the order was created

```bash
docker compose exec postgres \
  psql -U postgres -d chattosales -c \
  "SELECT id, state, amount, currency FROM orders;"
```

Expected:

```
 id (uuid) | state   | amount | currency
-----------+---------+--------+---------
 <UUID>    | inquiry |        | NGN
```

> `amount` is `NULL` at this stage — no items have been added yet.

Copy the order `id`:

```bash
ORDER_ID="<paste-uuid-here>"
```

---

### Step 4 — Add items to the order

```bash
curl -s -X POST "$BASE_URL/orders/$ORDER_ID/items" \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {"product_name": "Blue Sneakers", "quantity": 2, "unit_price": "5999.99"}
    ]
  }' | python3 -m json.tool
```

**Expected response (201):**

```json
{
  "id": "<ORDER_ID>",
  "state": "inquiry",
  "amount": "11999.98",
  "currency": "NGN",
  "items": [
    {
      "id": "<ITEM_UUID>",
      "product_name": "Blue Sneakers",
      "quantity": 2,
      "unit_price": "5999.99"
    }
  ]
}
```

---

### Step 5 — Confirm the order

The order must be in `CONFIRMED` state before a payment can be initiated.

```bash
curl -s -X POST "$BASE_URL/orders/$ORDER_ID/confirm" \
  | python3 -m json.tool
```

**Expected response:**

```json
{
  "id": "<ORDER_ID>",
  "state": "confirmed",
  "amount": "11999.98"
}
```

**Expected Redis event:**

```
order.state_changed   { "previous_state": "inquiry", "new_state": "confirmed" }
```

---

### Step 6 — Initiate payment

```bash
curl -s -X POST "$BASE_URL/payments/" \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "'"$ORDER_ID"'",
    "tenant_id": "'"$TENANT_ID"'"
  }' | python3 -m json.tool
```

**Expected response (201):**

```json
{
  "id": "<PAYMENT_UUID>",
  "tenant_id": "tenant-abc-123",
  "order_id": "<ORDER_ID>",
  "reference": "pay_<20-char-hex>",
  "amount": "11999.98",
  "currency": "NGN",
  "status": "pending",
  "provider": "paystack",
  "payment_link": "https://paystack.mock/pay/pay_<20-char-hex>",
  "created_at": "...",
  "updated_at": "..."
}
```

**Expected Redis event:**

```
payment.created   { "reference": "pay_xxx", "payment_link": "https://paystack.mock/pay/pay_xxx" }
```

Copy the `reference` field:

```bash
PAYMENT_REF="pay_<paste-reference-here>"
```

---

### Step 7 — Simulate Paystack payment webhook

In production, Paystack POSTs to this endpoint after the customer completes payment.
In development (`PAYSTACK_SECRET_KEY` is empty) the signature check is skipped.

```bash
curl -s -X POST "$BASE_URL/payments/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "charge.success",
    "data": {
      "reference": "'"$PAYMENT_REF"'",
      "status": "success",
      "amount": 1199998,
      "currency": "NGN"
    }
  }' | python3 -m json.tool
```

**Expected response:**

```json
{ "status": "received" }
```

**Expected Redis events (in sequence):**

```
payment.confirmed     ← emitted by PaymentService.handle_webhook()
order.state_changed   ← emitted by OrderService._do_paid_transition()
order.paid            ← emitted by OrderService._do_paid_transition()
```

> The `payment.confirmed` event is consumed by the `register_payment_confirmed_handler`
> background task, which transitions the order in a separate DB transaction. Allow ~1 s.

---

### Step 8 — Verify final state

**Payment table:**

```bash
docker compose exec postgres \
  psql -U postgres -d chattosales -c \
  "SELECT id, reference, status, amount FROM payments;"
```

Expected:

```
 id (uuid) | reference      | status  | amount
-----------+----------------+---------+---------
 <UUID>    | pay_<hex>      | success | 11999.98
```

**Order table:**

```bash
docker compose exec postgres \
  psql -U postgres -d chattosales -c \
  "SELECT id, state FROM orders WHERE id = '$ORDER_ID';"
```

Expected:

```
 id (uuid) | state
-----------+------
 <UUID>    | paid
```

---

### Step 9 — Complete the order

```bash
curl -s -X POST "$BASE_URL/orders/$ORDER_ID/complete" \
  | python3 -m json.tool
```

**Expected response:**

```json
{
  "id": "<ORDER_ID>",
  "state": "completed"
}
```

**Expected Redis event:**

```
order.state_changed   { "previous_state": "paid", "new_state": "completed" }
```

---

## Scenario 2 — Idempotency: Duplicate Webhook

Delivering the same Paystack webhook twice must not double-process the payment or
trigger a second order transition.

```bash
# First delivery — processed normally (already done in Scenario 1)
curl -s -X POST "$BASE_URL/payments/webhook" \
  -H "Content-Type: application/json" \
  -d '{"event":"charge.success","data":{"reference":"'"$PAYMENT_REF"'"}}' \
  | python3 -m json.tool
# → { "status": "received" }

# Second delivery — idempotent ignore
curl -s -X POST "$BASE_URL/payments/webhook" \
  -H "Content-Type: application/json" \
  -d '{"event":"charge.success","data":{"reference":"'"$PAYMENT_REF"'"}}' \
  | python3 -m json.tool
# → { "status": "received" }   (same 200 — not an error)
```

**Verification — payment row unchanged, still one record:**

```bash
docker compose exec postgres \
  psql -U postgres -d chattosales -c \
  "SELECT id, reference, status FROM payments WHERE reference = '$PAYMENT_REF';"
# → exactly one row, status = success
```

**What to check in logs:**

```
Payment already SUCCESS reference=pay_xxx — webhook ignored (idempotent)
```

```bash
docker compose logs app --tail 20 | grep idempotent
```

---

## Scenario 3 — Idempotency: Duplicate Inbound Message

Sending the same `message_id` twice must not insert a second `messages` row.

```bash
# Send the original message
curl -s -X POST "$BASE_URL/webhooks/webhook" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"'"$TENANT_ID"'","channel":"whatsapp","sender":"'"$SENDER"'","message":"I need help","message_id":"wamid.dup-001"}' \
  | python3 -m json.tool

# Re-send (simulates duplicate webhook delivery from the channel)
curl -s -X POST "$BASE_URL/webhooks/webhook" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"'"$TENANT_ID"'","channel":"whatsapp","sender":"'"$SENDER"'","message":"I need help","message_id":"wamid.dup-001"}' \
  | python3 -m json.tool
```

**Verification:**

```bash
docker compose exec postgres \
  psql -U postgres -d chattosales -c \
  "SELECT COUNT(*) FROM messages WHERE external_id = 'wamid.dup-001';"
# → count = 1
```

---

## Scenario 4 — Invalid State Transition (expect 409)

Attempting a transition that the state machine does not allow returns HTTP 409.

```bash
# Set up: create a new order and leave it in INQUIRY
curl -s -X POST "$BASE_URL/webhooks/webhook" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"'"$TENANT_ID"'","channel":"whatsapp","sender":"+2348000000001","message":"I want to order today","message_id":"wamid.inv-001"}' \
  | python3 -m json.tool

# Wait 1s, then get order id
sleep 1
docker compose exec postgres \
  psql -U postgres -d chattosales -c \
  "SELECT id, state FROM orders ORDER BY created_at DESC LIMIT 1;"
```

```bash
NEW_ORDER_ID="<paste-id>"

# Try to mark INQUIRY → PAID directly (not an allowed transition)
curl -s -X POST "$BASE_URL/orders/$NEW_ORDER_ID/pay" \
  | python3 -m json.tool
```

**Expected response — 409 Conflict:**

```json
{
  "error": "Invalid transition for order <id>: inquiry → paid."
}
```

**Other transitions that must also return 409:**

```bash
# COMPLETED → CONFIRMED
curl -s -X POST "$BASE_URL/orders/$ORDER_ID/confirm" | python3 -m json.tool
# → 409

# COMPLETED → PAID
curl -s -X POST "$BASE_URL/orders/$ORDER_ID/pay" | python3 -m json.tool
# → 409
```

---

## Scenario 5 — Payment for Non-CONFIRMED Order (expect 409)

Payment initiation is only allowed when the order is in `CONFIRMED` state.

```bash
# Use the INQUIRY order from Scenario 4
curl -s -X POST "$BASE_URL/payments/" \
  -H "Content-Type: application/json" \
  -d '{"order_id":"'"$NEW_ORDER_ID"'","tenant_id":"'"$TENANT_ID"'"}' \
  | python3 -m json.tool
```

**Expected response — 409 Conflict:**

```json
{
  "error": "Cannot initiate payment for an order in 'inquiry' state. Confirm the order first."
}
```

---

## Scenario 6 — Webhook for Unknown Reference

Paystack may occasionally send webhooks for references not in our database (e.g. test
events from the Paystack dashboard).

```bash
curl -s -X POST "$BASE_URL/payments/webhook" \
  -H "Content-Type: application/json" \
  -d '{"event":"charge.success","data":{"reference":"nonexistent-ref-xyz"}}' \
  | python3 -m json.tool
```

**Expected response — 200 (acknowledged, not an error):**

```json
{ "status": "received" }
```

**What to check in logs:**

```bash
docker compose logs app --tail 20 | grep "unknown payment reference"
# Webhook references unknown payment reference=nonexistent-ref-xyz — ignoring
```

No database rows are created or modified.

---

## Scenario 7 — Duplicate Payment Attempt for Same Order

Once a PENDING or SUCCESS payment exists for an order, a second initiation attempt
is rejected.

```bash
# Attempt to create a second payment for an order that already has one
curl -s -X POST "$BASE_URL/payments/" \
  -H "Content-Type: application/json" \
  -d '{"order_id":"'"$ORDER_ID"'","tenant_id":"'"$TENANT_ID"'"}' \
  | python3 -m json.tool
```

**Expected response — 409 Conflict:**

```json
{
  "error": "An active payment already exists for this order (reference=pay_xxx, status=success)."
}
```

---

## Scenario 8 — Order Without Items Cannot Be Paid

An order must have items (and therefore a non-null `amount`) before payment is initiated.

```bash
# Create a fresh order via message
curl -s -X POST "$BASE_URL/webhooks/webhook" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"'"$TENANT_ID"'","channel":"sms","sender":"+2348000000002","message":"I want to checkout now","message_id":"sms.noitem-001"}' \
  | python3 -m json.tool

sleep 1

# Get its id and confirm it (skipping items)
docker compose exec postgres \
  psql -U postgres -d chattosales -c \
  "SELECT id FROM orders ORDER BY created_at DESC LIMIT 1;"

NOITEM_ORDER_ID="<paste-id>"
curl -s -X POST "$BASE_URL/orders/$NOITEM_ORDER_ID/confirm" | python3 -m json.tool

# Attempt payment with no items
curl -s -X POST "$BASE_URL/payments/" \
  -H "Content-Type: application/json" \
  -d '{"order_id":"'"$NOITEM_ORDER_ID"'","tenant_id":"'"$TENANT_ID"'"}' \
  | python3 -m json.tool
```

**Expected response — 409 Conflict:**

```json
{
  "error": "Cannot initiate payment: order has no amount. Add items to the order first."
}
```

---

## Event Flow Reference

The complete ordered event sequence for a successful happy-path run:

| #   | Event name                   | Published by         | Consumed by                    |
| --- | ---------------------------- | -------------------- | ------------------------------ |
| 1   | `message.received`           | Ingestion service    | Conversation handler           |
| 2   | `conversation.message_saved` | Conversation handler | Order-intent handler           |
| 3   | `order.created`              | Order service        | (logging / future subscribers) |
| 4   | `order.state_changed`        | Order service        | (logging / future subscribers) |
| 5   | `payment.created`            | Payment service      | (logging / future subscribers) |
| 6   | `payment.confirmed`          | Payment service      | Payment-confirmed handler      |
| 7   | `order.state_changed`        | Order service        | (logging / future subscribers) |
| 8   | `order.paid`                 | Order service        | (logging / future subscribers) |

Subscribe to watch them all live:

```bash
docker compose exec redis redis-cli PSUBSCRIBE "chattosales.events.tenant-abc-123.*"
```

---

## Debugging Guide

### View application logs

```bash
# Stream live logs
docker compose logs -f app

# Last 50 lines
docker compose logs app --tail 50

# Filter for a specific order
docker compose logs app | grep "<ORDER_ID>"

# Filter for payment events
docker compose logs app | grep "payment"

# Filter for warnings and errors
docker compose logs app | grep -E "WARNING|ERROR"
```

### Inspect the database directly

```bash
# Open a psql shell
docker compose exec postgres psql -U postgres -d chattosales

# Useful queries:
SELECT id, phone_number, channel, status FROM conversations;
SELECT id, sender, content, external_id FROM messages;
SELECT id, conversation_id, state, amount, currency FROM orders;
SELECT id, order_id, product_name, quantity, unit_price FROM order_items;
SELECT id, order_id, reference, status, amount, payment_link FROM payments;
```

### Check Redis pub/sub live

```bash
# Subscribe to all events for the dev tenant
docker compose exec redis redis-cli PSUBSCRIBE "chattosales.events.tenant-abc-123.*"

# Subscribe to a single event type
docker compose exec redis redis-cli SUBSCRIBE "chattosales.events.tenant-abc-123.payment.confirmed"

# Count messages on a channel (approximate — published count)
docker compose exec redis redis-cli PUBSUB NUMSUB \
  "chattosales.events.tenant-abc-123.message.received"
```

### Common failure points

| Symptom                                | Likely cause                                                | Fix                                                                                    |
| -------------------------------------- | ----------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Order not created on first message     | Background handlers not started                             | Check `app/main.py` lifespan — ensure all three `register_*_handler` calls are present |
| `external_id` null in messages         | `message_id` not sent in webhook body                       | Include `"message_id"` field in inbound webhook payload                                |
| Payment initiation returns 409         | Order not CONFIRMED, or already has payment                 | Confirm the order first; check existing payments table                                 |
| Webhook returns 401                    | `PAYSTACK_SECRET_KEY` is set but signature is missing/wrong | In dev leave `PAYSTACK_SECRET_KEY=""` in `.env.docker`                                 |
| Order stuck in CONFIRMED after webhook | `payment.confirmed` handler not running                     | Check lifespan — `register_payment_confirmed_handler` must be registered               |
| Schema errors on startup               | Stale database volume                                       | `docker compose down -v && docker compose up --build -d`                               |

---

## Demo Script

Use this script when presenting the system to stakeholders.

> "The customer sends a WhatsApp message saying 'I want to buy the blue sneakers'.
> The system immediately publishes a `message.received` event on the Redis bus.
> The conversation handler picks this up, stores the conversation and the message
> in PostgreSQL, then publishes `conversation.message_saved`.
>
> The order-intent handler receives that event, detects the keyword 'buy', and
> automatically creates an INQUIRY order — no human intervention required.
>
> The operator (or a future AI agent) reviews the order, adds the item, and
> confirms it. The payment service generates a Paystack checkout link in
> milliseconds and stores a PENDING payment record.
>
> When the customer pays, Paystack fires a `charge.success` webhook to our
> `/payments/webhook` endpoint. We verify the signature, mark the payment SUCCESS,
> and publish a `payment.confirmed` event. The background handler picks that up
> and transitions the order to PAID — all without any polling or direct coupling
> between the services.
>
> The entire flow, from message to paid order, is observable in real time via the
> Redis event stream."

---

## Quick Reference — All Endpoints

| Method | Path                           | Purpose                              |
| ------ | ------------------------------ | ------------------------------------ |
| `GET`  | `/health`                      | Health check                         |
| `POST` | `/api/v1/webhooks/webhook`     | Ingest normalised inbound message    |
| `POST` | `/api/v1/webhooks/whatsapp`    | Receive raw Meta Cloud API webhook   |
| `GET`  | `/api/v1/webhooks/whatsapp`    | WhatsApp challenge verification      |
| `POST` | `/api/v1/orders/`              | Create order with items (HTTP)       |
| `GET`  | `/api/v1/orders/{id}`          | Get order by ID                      |
| `POST` | `/api/v1/orders/{id}/items`    | Add items to existing order          |
| `POST` | `/api/v1/orders/{id}/confirm`  | Transition INQUIRY → CONFIRMED       |
| `POST` | `/api/v1/orders/{id}/pay`      | Transition CONFIRMED → PAID (manual) |
| `POST` | `/api/v1/orders/{id}/complete` | Transition PAID → COMPLETED          |
| `POST` | `/api/v1/orders/{id}/fail`     | Transition any open state → FAILED   |
| `POST` | `/api/v1/payments/`            | Initiate Paystack payment for order  |
| `GET`  | `/api/v1/payments/{id}`        | Get payment by ID                    |
| `POST` | `/api/v1/payments/webhook`     | Receive Paystack payment webhook     |
| —      | `http://localhost:8000/docs`   | Swagger UI (development only)        |
