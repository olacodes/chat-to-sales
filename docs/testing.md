# Testing Guide

This document covers running the automated test suite and manually exercising the full
ingestion → conversation → order pipeline locally.

---

## 1. Automated Tests

### Prerequisites

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

No running infrastructure is required — all external dependencies (Redis, PostgreSQL) are
handled by in-memory fakes and `AsyncMock` in the test suite.

### Running all tests

```bash
pytest -v
```

### Running a specific module

```bash
pytest tests/test_health.py -v
pytest tests/test_ingestion.py -v
pytest tests/test_event_bus.py -v
```

### Coverage report

```bash
pytest --cov=app --cov-report=term-missing
```

---

## 2. Manual Testing (Docker)

### Start the full stack (always use a fresh volume for a clean schema)

```bash
docker compose down -v && docker compose up --build -d
```

Wait until all healthchecks pass:

```bash
docker compose ps
# all services should show "healthy" or "running"
```

> `create_all_tables()` runs automatically at startup via the lifespan hook — no manual
> migration step is needed in development.

---

## 3. Health Check

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

**Expected response:**

```json
{
  "status": "ok",
  "environment": "development",
  "version": "0.1.0"
}
```

---

## 4. Ingest a Message (channel-agnostic webhook)

**Endpoint:** `POST /api/v1/webhooks/webhook`

Request fields:

| Field        | Type                 | Required | Description                                                        |
| ------------ | -------------------- | -------- | ------------------------------------------------------------------ |
| `channel`    | `whatsapp\|sms\|web` | ✅       | Source channel                                                     |
| `sender`     | `string`             | ✅       | E.164 phone number or opaque web session ID                        |
| `message`    | `string`             | ✅       | Raw message text (1–4096 chars)                                    |
| `tenant_id`  | `string`             | ✅       | Owning tenant identifier                                           |
| `message_id` | `string`             | ❌       | Channel-assigned ID (e.g. WhatsApp `wamid`) used for deduplication |

### WhatsApp inbound message

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "tenant-abc-123",
    "channel": "whatsapp",
    "sender": "+2348012345678",
    "message": "Hello, I want to place an order",
    "message_id": "wamid.test001"
  }' | python3 -m json.tool
```

**Expected response (202 Accepted):**

```json
{
  "channel": "whatsapp",
  "sender": "+2348012345678",
  "message": "Hello, I want to place an order",
  "message_lower": "hello, i want to place an order",
  "word_count": 8,
  "tenant_id": "tenant-abc-123",
  "is_empty": false
}
```

### SMS inbound message

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "tenant-abc-123",
    "channel": "sms",
    "sender": "+2348099887766",
    "message": "What items do you have?"
  }' | python3 -m json.tool
```

### Web chat message

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "tenant-abc-123",
    "channel": "web",
    "sender": "user-session-xyz",
    "message": "Can I track my order?"
  }' | python3 -m json.tool
```

---

## 5. WhatsApp Meta Cloud API Webhook

### Challenge verification (GET)

```bash
VERIFY_TOKEN="your-verify-token"  # must match WHATSAPP_VERIFY_TOKEN in .env.docker

curl -s "http://localhost:8000/api/v1/webhooks/whatsapp?\
hub.mode=subscribe&\
hub.verify_token=${VERIFY_TOKEN}&\
hub.challenge=test-challenge-string"
# → test-challenge-string
```

---

## 6. Verify Redis Events

Use pattern-subscribe so you catch all events for a tenant in one session:

```bash
docker compose exec redis redis-cli PSUBSCRIBE "chattosales.events.tenant-abc-123.*"
```

In a second terminal, send a webhook request (section 4). You should see the
`message.received` event arrive. After the order intent handler fires you will also see
`order.created` and `order.state_changed` events on the same subscription.

---

## 7. End-to-End Flow

This section walks the full pipeline from a raw inbound message through conversation
persistence to order state-machine transitions.

### Step 1 — Fresh environment

```bash
docker compose down -v && docker compose up --build -d
```

### Step 2 — Open a Redis event monitor (optional but recommended)

```bash
docker compose exec redis redis-cli PSUBSCRIBE "chattosales.events.tenant-abc-123.*"
```

Leave this terminal open. All events published during the flow will appear here.

### Step 3 — Send a message that triggers an order

The order-intent handler detects keywords: `order`, `buy`, `purchase`, `want`, `get me`,
`i need`, `checkout`.

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "tenant-abc-123",
    "channel": "whatsapp",
    "sender": "+2348012345678",
    "message": "I want to buy 2 units of the blue sneakers",
    "message_id": "wamid.e2e-001"
  }' | python3 -m json.tool
```

After the 202 response, the background listener tasks (conversation handler + order-intent
handler) process the `message.received` event asynchronously. Allow ~1 second for them to
complete.

### Step 4 — Verify conversation and message were persisted

```bash
docker compose exec postgres \
  psql -U postgres -d chattosales -c \
  "SELECT id, phone_number, channel, status FROM conversations;"

docker compose exec postgres \
  psql -U postgres -d chattosales -c \
  "SELECT id, sender, content, external_id FROM messages;"
```

`external_id` will match the `message_id` you provided (`wamid.e2e-001`).

### Step 5 — Verify the order was created

```bash
docker compose exec postgres \
  psql -U postgres -d chattosales -c \
  "SELECT id, state, conversation_id, amount, currency FROM orders;"
```

The order should be in `INQUIRY` state. Copy the `id` — you will use it in the next steps.

### Step 6 — Advance the order through the state machine

Replace `<ORDER_ID>` with the UUID from step 5.

**Confirm the order:**

```bash
curl -s -X POST http://localhost:8000/api/v1/orders/<ORDER_ID>/confirm \
  | python3 -m json.tool
# state → CONFIRMED; emits order.state_changed event
```

**Mark as paid:**

```bash
curl -s -X POST http://localhost:8000/api/v1/orders/<ORDER_ID>/pay \
  | python3 -m json.tool
# state → PAID; emits order.state_changed AND order.paid events
```

**Complete the order:**

```bash
curl -s -X POST http://localhost:8000/api/v1/orders/<ORDER_ID>/complete \
  | python3 -m json.tool
# state → COMPLETED; emits order.state_changed event
```

### Step 7 — Verify final state in the database

```bash
docker compose exec postgres \
  psql -U postgres -d chattosales -c \
  "SELECT id, state FROM orders WHERE id = '<ORDER_ID>';"
```

### Step 8 — Trigger an invalid transition (expect 409)

Attempting to move a `COMPLETED` order to `CONFIRMED` should fail:

```bash
curl -s -X POST http://localhost:8000/api/v1/orders/<ORDER_ID>/confirm \
  | python3 -m json.tool
# → 409 Conflict
```

### Step 9 — Idempotency check (same message_id)

Sending the same `message_id` twice should not create a duplicate message:

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "tenant-abc-123",
    "channel": "whatsapp",
    "sender": "+2348012345678",
    "message": "I want to buy 2 units of the blue sneakers",
    "message_id": "wamid.e2e-001"
  }' | python3 -m json.tool
# 202 response — but no new Message row is inserted (duplicate dropped silently)
```

```bash
docker compose exec postgres \
  psql -U postgres -d chattosales -c \
  "SELECT COUNT(*) FROM messages WHERE external_id = 'wamid.e2e-001';"
# → count = 1
```

---

## 8. API Documentation

| Interface    | URL                                |
| ------------ | ---------------------------------- |
| Swagger UI   | http://localhost:8000/docs         |
| ReDoc        | http://localhost:8000/redoc        |
| OpenAPI JSON | http://localhost:8000/openapi.json |

---

## 9. Validation Error Examples

ChatToSales returns RFC 7807-style error responses for invalid input.

### Missing required field

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel": "whatsapp"}' | python3 -m json.tool
# → 422 Unprocessable Entity with field-level error details
```

### Empty message body

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "tenant-abc-123",
    "channel": "whatsapp",
    "sender": "+2348012345678",
    "message": "   "
  }' | python3 -m json.tool
# → 422: message must not be empty after stripping whitespace
```

---

## 10. Stopping the Stack

```bash
docker compose down          # stop containers, keep volumes
docker compose down -v       # stop containers AND delete volumes (fresh state)
```
