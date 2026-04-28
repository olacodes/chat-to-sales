# Feature 2: Intelligent Order Management — Testing Guide

This document is the step-by-step test specification for Feature 2.
Follow every step in order. Do not skip prerequisites.

---

## 1. System Architecture Recap

```
Customer/Trader sends WhatsApp message
        |
        v
POST /api/v1/webhooks/webhook   <-- test entry point
        |
        v
IngestionService publishes  message.received  event
        |
        v
ConversationService persists the message, publishes  conversation.message_saved  event
        |
        v
+-------------------------------+     +----------------------------+
| onboarding handler            |     | order handler              |
| (handles in-progress traders) |     | (handles orders)           |
+-------------------------------+     +----------------------------+
                                              |
                             +----------------+-----------------+
                             |                                  |
                     Sender is TRADER                  Sender is CUSTOMER
                             |                                  |
                  handle_trader_command()         handle_inbound_customer_message()
                  CONFIRM/CANCEL/PAID/DELIVERED   NLP -> summary -> session
```

Redis keys written by the order module:
- `order:session:{tenant_id}:{customer_phone}` — customer in-flight order (TTL 24 h)
- `trader:phone:{phone_number}` — trader identity cache keyed by personal phone (TTL 1 h)
- `trader:tenant:{tenant_id}` — trader identity cache keyed by tenant (TTL 1 h)

Order state machine:
```
INQUIRY -> CONFIRMED -> PAID -> COMPLETED
       \-> FAILED              \-> FAILED
CONFIRMED \-> FAILED
CONFIRMED \-> COMPLETED   (DELIVERED shortcut)
```

---

## 2. Prerequisites

### 2.1 Environment variables

`.env` must have these values set before you start:

```
TENANT_ID=tenant-abc-123            # used by the ingestion router
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/chattosales
REDIS_URL=redis://localhost:6379/0
ANTHROPIC_API_KEY=sk-ant-...        # required for Claude NLP Layer 2 fallback
OPENAI_API_KEY=sk-...               # required for voice note transcription
ENCRYPTION_KEY=<fernet-key>         # required for WhatsApp channel credentials
```

`WHATSAPP_APP_SECRET` can be left **empty** — this disables HMAC checking on the
raw WhatsApp endpoint and is safe for local testing.

To test WhatsApp reply delivery, you also need a real WhatsApp channel registered:
```
WHATSAPP_PHONE_NUMBER_ID=<your_phone_number_id>
WHATSAPP_ACCESS_TOKEN=<your_access_token>
```

If those are not set, the app still works end-to-end except the outgoing
WhatsApp messages will fail (the `notifications` row will be marked `FAILED`).
You can still verify all the state machine logic and Redis/DB state without them.

### 2.2 A completed trader in the database

**Feature 2 requires a Trader row with `onboarding_status = 'complete'` and a
`tenant_id` that matches your `TENANT_ID` setting.**

If you completed Feature 1 onboarding for a trader under `TENANT_ID=tenant-abc-123`,
that row already exists. If not, insert one manually:

```sql
-- Replace phone numbers and values as needed.
INSERT INTO traders (
    id, phone_number, business_name, business_category,
    store_slug, tenant_id, onboarding_status, tier, onboarding_catalogue,
    created_at, updated_at
) VALUES (
    gen_random_uuid()::text,
    '2348012345678',                              -- trader's personal phone (E.164, no +)
    'Mama Caro Provisions',
    'provisions',
    'mama-caro-provisions',
    'tenant-abc-123',                             -- must match TENANT_ID in .env
    'complete',
    'ofe',
    '{"Indomie Carton": 8500, "Rice 50kg": 63000, "Peak Milk Tin": 4200}',
    now(), now()
);
```

Verify it was inserted:
```sql
SELECT id, phone_number, business_name, tenant_id, onboarding_status
FROM traders
WHERE tenant_id = 'tenant-abc-123';
```

Save the trader's phone number — you will use it for trader commands.
Save your test customer phone (anything that is NOT the trader's phone), e.g. `2348099887766`.

### 2.3 WhatsApp channel record (for outgoing replies)

If testing with real WhatsApp delivery:
```sql
-- The channel record must exist so NotificationService can look up credentials.
SELECT tenant_id, channel, phone_number_id
FROM tenant_channels
WHERE tenant_id = 'tenant-abc-123' AND channel = 'whatsapp';
```

If the row does not exist, register one via the API or insert directly (the
access token must be Fernet-encrypted using your `ENCRYPTION_KEY`).

---

## 3. Start the Stack

```bash
# Terminal 1 — application
source venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Redis
redis-server

# Terminal 3 — PostgreSQL (if running locally)
pg_ctl start -D /usr/local/var/postgresql@14
```

Check the startup logs in Terminal 1. You must see all of these lines:

```
INFO  Redis connection established.
INFO  Database tables verified/created
INFO  Registering message.received handler (all tenants)
INFO  Registering onboarding handler (all tenants)
INFO  Registering order-intent handler (all tenants)
INFO  Registering credit_sale.status_changed handler (all tenants)
INFO  Registering payment confirmed handler (all tenants)
INFO  Event listeners started (all tenants via pattern subscription)
```

If `Registering order-intent handler` is missing, `main.py` was not updated — check that `register_order_intent_handler` is called in `lifespan`.

Health check:
```bash
curl http://localhost:8000/health
# Expected: {"status":"ok","app":"ChatToSales",...}
```

---

## 4. How to Send a Simulated WhatsApp Message

All tests use the channel-agnostic webhook endpoint — no HMAC signature required.

```
POST http://localhost:8000/api/v1/webhooks/webhook
Content-Type: application/json
```

Base payload template:
```json
{
  "channel": "whatsapp",
  "sender_identifier": "<SENDER_PHONE>",
  "message": "<MESSAGE_TEXT>",
  "tenant_id": "tenant-abc-123",
  "message_id": "<UNIQUE_ID>"
}
```

Replace:
- `<SENDER_PHONE>` — E.164 phone without `+` (e.g. `2348099887766`)
- `<MESSAGE_TEXT>` — the message text
- `<UNIQUE_ID>` — any unique string per message (e.g. `msg-001`); used for deduplication

For audio (voice note) messages, add media fields and use `[audio]` as the message:
```json
{
  "channel": "whatsapp",
  "sender_identifier": "2348099887766",
  "message": "[audio]",
  "tenant_id": "tenant-abc-123",
  "message_id": "msg-audio-001",
  "media_id": "<META_MEDIA_ID>",
  "media_type": "audio/ogg"
}
```

Expected HTTP response for every valid message:
```json
{"channel":"whatsapp","sender_identifier":"...","message":"...","message_lower":"...","word_count":N,"tenant_id":"...","is_empty":false}
```
HTTP `200 OK`. The actual order processing happens asynchronously via Redis pub/sub after the response returns.

---

## 5. Scenario 1 — Full Happy Path (Text Order, Layer 1 NLP)

This tests the complete order lifecycle from first customer message to delivery.

### Step 1-A: Customer sends a simple order

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348099887766",
    "message": "I want 2 Indomie Carton and 1 Rice 50kg",
    "tenant_id": "tenant-abc-123",
    "message_id": "sc1-msg-001"
  }'
```

**Wait 1–2 seconds** for async processing, then verify:

**Application logs — what to look for:**
```
INFO  Order handler: customer message sender=2348099887766 event_id=...
INFO  Order summary shown to customer order_id=<UUID> customer=2348099887766 total=80000
```

**Redis — customer session created:**
```bash
redis-cli GET "order:session:tenant-abc-123:2348099887766"
```
Expected value (pretty-printed):
```json
{
  "state": "awaiting_customer_confirmation",
  "order_id": "<UUID>",
  "items": [
    {"name": "Indomie Carton", "qty": 2, "unit_price": 8500},
    {"name": "Rice 50kg", "qty": 1, "unit_price": 63000}
  ],
  "total": 80000
}
```

**PostgreSQL — INQUIRY order created:**
```sql
SELECT id, state, customer_phone, amount, currency
FROM orders
WHERE tenant_id = 'tenant-abc-123' AND customer_phone = '2348099887766'
ORDER BY created_at DESC
LIMIT 1;
```
Expected: `state = 'inquiry'`, `amount = 80000.00`, `currency = 'NGN'`.

```sql
SELECT product_name, quantity, unit_price
FROM order_items
WHERE order_id = '<UUID from above>';
```
Expected: 2 rows — `Indomie Carton x 2 @ 8500` and `Rice 50kg x 1 @ 63000`.

**WhatsApp reply to customer (if configured):**
```
Here is your order from *Mama Caro Provisions*:

  2x Indomie Carton - N8,500 each = N17,000
  1x Rice 50kg - N63,000 each = N63,000

*Total: N80,000*

Is this correct? Reply *YES* to confirm or *NO* to cancel.
```

Note: Save the first 8 characters of the order UUID — this is the `order_ref` used in trader commands.
Example: if UUID is `3f8a2c1b-0e5d-4f7a-9b8c-1234567890ab`, the ref is `3f8a2c1b`.

---

### Step 1-B: Customer confirms the order

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348099887766",
    "message": "yes",
    "tenant_id": "tenant-abc-123",
    "message_id": "sc1-msg-002"
  }'
```

**Wait 1–2 seconds**, then verify:

**Application logs:**
```
INFO  Order handler: customer message sender=2348099887766 event_id=...
INFO  Customer confirmed order order_id=<UUID> customer=2348099887766
```

**Redis — customer session cleared:**
```bash
redis-cli GET "order:session:tenant-abc-123:2348099887766"
# Expected: (nil)
```

**PostgreSQL — order still INQUIRY (trader has not confirmed yet):**
```sql
SELECT state FROM orders WHERE id = '<UUID>';
-- Expected: inquiry
```

**WhatsApp reply to customer:**
```
Your order has been sent to *Mama Caro Provisions*! I will let you know once they confirm it. Please hold on. 🙏
```

**WhatsApp notification to trader (sent to `2348012345678`):**
```
🛒 New order from +2348099887766:

  2x Indomie Carton - N8,500 each = N17,000
  1x Rice 50kg - N63,000 each = N63,000

*Total: N80,000*
Ref: 3f8a2c1b

Reply *CONFIRM 3f8a2c1b* to accept
Reply *CANCEL 3f8a2c1b* to decline
```

---

### Step 1-C: Trader confirms the order

Send this from the **trader's phone number** (`2348012345678`):

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348012345678",
    "message": "CONFIRM 3f8a2c1b",
    "tenant_id": "tenant-abc-123",
    "message_id": "sc1-msg-003"
  }'
```

Replace `3f8a2c1b` with the actual first 8 chars of the order UUID from Step 1-A.
The command is case-insensitive — `confirm 3f8a2c1b` works too.

**Application logs:**
```
INFO  Order handler: trader command sender=2348012345678 event_id=...
INFO  Order transition order_id=<UUID> inquiry -> confirmed
INFO  Trader confirmed order_id=<UUID> ref=3f8a2c1b
```

**PostgreSQL — order transitions to CONFIRMED:**
```sql
SELECT state FROM orders WHERE id = '<UUID>';
-- Expected: confirmed
```

**WhatsApp reply to trader:**
```
✅ Order 3f8a2c1b confirmed. Customer don hear about am.
```

**WhatsApp reply to customer:**
```
✅ *Mama Caro Provisions* don confirm your order!

Total: N80,000

They go reach out to you for delivery or pickup details. Thank you! 🙏
```

---

### Step 1-D: Trader marks order as paid

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348012345678",
    "message": "PAID 3f8a2c1b",
    "tenant_id": "tenant-abc-123",
    "message_id": "sc1-msg-004"
  }'
```

**PostgreSQL:**
```sql
SELECT state FROM orders WHERE id = '<UUID>';
-- Expected: paid
```

**WhatsApp reply to trader:**
```
💰 Payment recorded for order 3f8a2c1b. Order don mark as PAID.
```

---

### Step 1-E: Trader marks order as delivered

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348012345678",
    "message": "DELIVERED 3f8a2c1b",
    "tenant_id": "tenant-abc-123",
    "message_id": "sc1-msg-005"
  }'
```

**PostgreSQL:**
```sql
SELECT state FROM orders WHERE id = '<UUID>';
-- Expected: completed
```

**WhatsApp reply to trader:**
```
🚀 Order 3f8a2c1b mark as delivered. Well done! 💪
```

Attempting any further state change on this order (e.g. `CONFIRM 3f8a2c1b` again)
must fail. Test it:
```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348012345678",
    "message": "CONFIRM 3f8a2c1b",
    "tenant_id": "tenant-abc-123",
    "message_id": "sc1-msg-006"
  }'
```
**Expected:** Trader receives a "Cannot confirm order..." error reply.
The order state remains `completed` — verify in PostgreSQL.

---

## 6. Scenario 2 — Customer Cancels

Start fresh — reset Redis session if there is one from a previous test:
```bash
redis-cli DEL "order:session:tenant-abc-123:2348099887766"
```

### Step 2-A: Customer sends an order

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348099887766",
    "message": "I want 3 Peak Milk Tin",
    "tenant_id": "tenant-abc-123",
    "message_id": "sc2-msg-001"
  }'
```

Wait for the order summary to be sent to the customer.
Verify in Redis that `order:session:tenant-abc-123:2348099887766` exists with `state = awaiting_customer_confirmation`.

### Step 2-B: Customer cancels

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348099887766",
    "message": "no",
    "tenant_id": "tenant-abc-123",
    "message_id": "sc2-msg-002"
  }'
```

**Verify:**
```bash
redis-cli GET "order:session:tenant-abc-123:2348099887766"
# Expected: (nil)
```

```sql
SELECT state FROM orders WHERE customer_phone = '2348099887766' ORDER BY created_at DESC LIMIT 1;
-- Expected: failed
```

**WhatsApp reply to customer:**
```
Your order with *Mama Caro Provisions* don cancel.

If you want to order something else, just message me anytime. 👍
```

---

## 7. Scenario 3 — Trader Cancels

### Step 3-A: Customer sends and confirms an order

Repeat Steps 1-A and 1-B to get an INQUIRY order.
Note the order ref (first 8 chars of UUID).

### Step 3-B: Trader cancels

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348012345678",
    "message": "CANCEL <order_ref>",
    "tenant_id": "tenant-abc-123",
    "message_id": "sc3-msg-001"
  }'
```

**Verify:**
```sql
SELECT state FROM orders WHERE id = '<UUID>';
-- Expected: failed
```

**WhatsApp reply to trader:**
```
❌ Order <ref> cancelled. Customer don hear about am.
```

**WhatsApp reply to customer:**
```
Your order with *Mama Caro Provisions* don cancel.

If you want to order something else, just message me anytime. 👍
```

---

## 8. Scenario 4 — Delivered Without Going Through PAID (CONFIRM → DELIVERED)

Some traders deliver first and collect payment later. Test that CONFIRMED → COMPLETED
works directly.

### Step 4-A: Get an order to CONFIRMED state

Repeat Steps 1-A, 1-B, and 1-C to create a CONFIRMED order.

### Step 4-B: Trader marks as delivered without marking paid first

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348012345678",
    "message": "DELIVERED <order_ref>",
    "tenant_id": "tenant-abc-123",
    "message_id": "sc4-msg-001"
  }'
```

**PostgreSQL:**
```sql
SELECT state FROM orders WHERE id = '<UUID>';
-- Expected: completed
```

---

## 9. Scenario 5 — Pidgin Order (Layer 2 NLP / Claude Haiku)

This tests the Claude fallback for messages that Layer 1 cannot parse into items.

**Prerequisite:** `ANTHROPIC_API_KEY` must be set.

```bash
redis-cli DEL "order:session:tenant-abc-123:2348099887766"

curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348099887766",
    "message": "abeg I need Indomie carton meji and rice 50kg one",
    "tenant_id": "tenant-abc-123",
    "message_id": "sc5-msg-001"
  }'
```

The message `"meji"` (Yoruba for 2) will cause Layer 1 to find items but fail on `meji`.
Claude will interpret it as 2.

**Application logs — Layer 2 called:**
```
INFO  Order summary shown to customer order_id=<UUID> customer=2348099887766 total=80000
```

If you do NOT see any log about Claude failing, the fallback worked.

**PostgreSQL:**
```sql
SELECT oi.product_name, oi.quantity
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
WHERE o.customer_phone = '2348099887766'
ORDER BY o.created_at DESC;
-- Expected: Indomie Carton x 2, Rice 50kg x 1
```

Another Pidgin test (no items extractable by Layer 1):
```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348099887766",
    "message": "I dey look for some indomie and rice o",
    "tenant_id": "tenant-abc-123",
    "message_id": "sc5-msg-002"
  }'
```

Layer 1 will detect order intent (`dey look for`) but find no items (no quantity prefix).
Layer 2 will be called. If Claude can extract items from the catalogue, a summary appears.
If it needs clarification, Claude sets `clarification_needed=true` and the customer gets
a clarification question.

---

## 10. Scenario 6 — Voice Note Order

**Prerequisite:** `OPENAI_API_KEY` set, a real Meta `media_id` for an audio file.
In production, this `media_id` comes from the WhatsApp webhook. For testing without
a real media file, skip this scenario or mock the transcription.

To test end-to-end with a real voice note:
1. Send a voice note to your WhatsApp Business number.
2. The Meta webhook fires and the `audio` message object contains the `media_id`.
3. The ingestion router sets `content = "[audio]"` and passes `media_id` and `media_type`.

Simulating with a real `media_id`:
```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348099887766",
    "message": "[audio]",
    "tenant_id": "tenant-abc-123",
    "message_id": "sc6-msg-001",
    "media_id": "<REAL_META_MEDIA_ID>",
    "media_type": "audio/ogg"
  }'
```

**Application logs to verify transcription happened:**
```
INFO  Whisper transcribed N chars from audio/ogg audio
INFO  Order handler: audio transcribed N chars sender=2348099887766
INFO  Order summary shown to customer order_id=<UUID> ...
```

If transcription fails (empty result), the customer receives:
```
I no fit hear that voice note well well. 😅

Abeg type your order or send a clearer voice note.
```

---

## 11. Edge Cases

### 11.1 — Customer says YES with no active session

```bash
redis-cli DEL "order:session:tenant-abc-123:2348099887766"

curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348099887766",
    "message": "yes",
    "tenant_id": "tenant-abc-123",
    "message_id": "edge-001"
  }'
```

**Expected WhatsApp reply:**
```
No active order to cancel.

If you want to order something, just tell me what you need! 😊
```

No order should be created in the database.

---

### 11.2 — Customer sends a greeting / unknown message

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348099887766",
    "message": "good morning",
    "tenant_id": "tenant-abc-123",
    "message_id": "edge-002"
  }'
```

**Expected WhatsApp reply:**
```
I no understand wetin you want o. 🤔

To place an order, just tell me what you need. For example:
_I want 2 cartons of Indomie and 1 bag of rice_
```

No order, no Redis session created.

---

### 11.3 — Customer orders a product not in the catalogue

The catalogue has `Indomie Carton`, `Rice 50kg`, `Peak Milk Tin`.
Order a product that is NOT in it:

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348099887766",
    "message": "I want 5 Garri bags",
    "tenant_id": "tenant-abc-123",
    "message_id": "edge-003"
  }'
```

**Expected WhatsApp reply:**
```
I see these items in your order but I no have their prices:

  - Garri bags

Abeg type the quantities and prices. For example:
_2 cartons Indomie = 8500, 1 bag rice = 63000_
```

No order is created in the database (order is only created when all prices are known).
Verify:
```bash
redis-cli GET "order:session:tenant-abc-123:2348099887766"
# Expected: (nil)   — no session stored because we didn't get to the summary step
```

---

### 11.4 — Trader sends CONFIRM with a wrong or non-existent ref

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348012345678",
    "message": "CONFIRM xxxxxxxx",
    "tenant_id": "tenant-abc-123",
    "message_id": "edge-004"
  }'
```

**Expected WhatsApp reply to trader:**
```
I no fit find order with ref xxxxxxxx.

Check the exact ref code from the order notification and try again.
```

---

### 11.5 — Trader sends unknown text (no command keyword)

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348012345678",
    "message": "hello how are you",
    "tenant_id": "tenant-abc-123",
    "message_id": "edge-005"
  }'
```

**Expected WhatsApp reply to trader:**
```
To manage your orders, use these commands:

  CONFIRM <ref>   - confirm a customer order
  CANCEL <ref>    - cancel an order
  PAID <ref>      - mark order as paid
  DELIVERED <ref> - mark order as delivered

The ref is the short code shown in each order notification.

Visit your dashboard to see all orders.
```

---

### 11.6 — Sender is a trader still in onboarding (must be skipped by order handler)

Create an active onboarding session in Redis for a phone number that is NOT a
completed trader:

```bash
redis-cli SET "onboarding:state:2348055551234" '{"step":"awaiting_name","data":{}}' EX 604800
```

Now send a message from that phone:
```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348055551234",
    "message": "I want 2 Indomie",
    "tenant_id": "tenant-abc-123",
    "message_id": "edge-006"
  }'
```

**Application logs — order handler must skip:**
```
DEBUG Order handler: sender=2348055551234 is in onboarding — skipping event_id=...
```

The onboarding handler handles it instead (sends the name-collection step).
No order or order session created.

```bash
redis-cli DEL "onboarding:state:2348055551234"   # clean up
```

---

### 11.7 — Customer sends a non-YES/NO message while awaiting confirmation

After Step 1-A (order summary sent, session is `awaiting_customer_confirmation`):

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348099887766",
    "message": "how much is the rice?",
    "tenant_id": "tenant-abc-123",
    "message_id": "edge-007"
  }'
```

**Expected:** The order summary is re-sent to the customer.
The Redis session is NOT cleared. The order remains in the database as INQUIRY.

Verify:
```bash
redis-cli GET "order:session:tenant-abc-123:2348099887766"
# Expected: still present with state=awaiting_customer_confirmation
```

---

### 11.8 — Duplicate message (same message_id sent twice)

Send Step 1-A again with the exact same `message_id`:
```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348099887766",
    "message": "I want 2 Indomie Carton and 1 Rice 50kg",
    "tenant_id": "tenant-abc-123",
    "message_id": "sc1-msg-001"
  }'
```

**Application logs:**
```
INFO  Duplicate message dropped event_id=... conversation_id=...
```

No second order is created. The notification idempotency key also prevents a
second WhatsApp message from being sent.

---

## 12. Redis State Inspection

### View a customer order session
```bash
redis-cli GET "order:session:tenant-abc-123:2348099887766"
```

### View a trader identity cache entry (by phone)
```bash
redis-cli GET "trader:phone:2348012345678"
```

### View a trader identity cache entry (by tenant)
```bash
redis-cli GET "trader:tenant:tenant-abc-123"
```

### List all order session keys
```bash
redis-cli KEYS "order:session:*"
```

### List all trader cache keys
```bash
redis-cli KEYS "trader:*"
```

### Check TTL remaining on a session
```bash
redis-cli TTL "order:session:tenant-abc-123:2348099887766"
# Expected: a value up to 86400 (24 hours in seconds)
```

### Manually clear a customer session (for re-testing)
```bash
redis-cli DEL "order:session:tenant-abc-123:2348099887766"
```

### Manually clear the trader cache (forces a DB reload on next message)
```bash
redis-cli DEL "trader:phone:2348012345678"
redis-cli DEL "trader:tenant:tenant-abc-123"
```

---

## 13. PostgreSQL Verification

### All orders for the test tenant
```sql
SELECT id, state, customer_phone, amount, currency, created_at, updated_at
FROM orders
WHERE tenant_id = 'tenant-abc-123'
ORDER BY created_at DESC;
```

### Items on a specific order
```sql
SELECT product_name, quantity, unit_price
FROM order_items
WHERE order_id = '<UUID>';
```

### Check the trader row
```sql
SELECT phone_number, business_name, tenant_id, onboarding_status, onboarding_catalogue
FROM traders
WHERE tenant_id = 'tenant-abc-123';
```

### Notifications sent for an order
```sql
SELECT recipient, message_text, status, created_at
FROM notifications
WHERE order_id = '<UUID>'
ORDER BY created_at;
```

### All notifications sent today
```sql
SELECT recipient, LEFT(message_text, 60) AS preview, status, created_at
FROM notifications
WHERE tenant_id = 'tenant-abc-123'
  AND created_at > now() - INTERVAL '1 day'
ORDER BY created_at DESC;
```

---

## 14. Full Order Reset Procedure

Use between test scenarios to start completely fresh.

```bash
# 1. Clear Redis sessions and caches
redis-cli DEL "order:session:tenant-abc-123:2348099887766"
redis-cli DEL "trader:phone:2348012345678"
redis-cli DEL "trader:tenant:tenant-abc-123"

# 2. Optionally delete all test orders from PostgreSQL
# (only do this in development — never in production)
```

```sql
-- Delete order items first (FK constraint)
DELETE FROM order_items
WHERE order_id IN (
    SELECT id FROM orders WHERE tenant_id = 'tenant-abc-123'
);

-- Delete orders
DELETE FROM orders WHERE tenant_id = 'tenant-abc-123';

-- Delete test notifications
DELETE FROM notifications WHERE tenant_id = 'tenant-abc-123';
```

---

## 15. Log Inspection Guide

### What healthy processing looks like

For a customer order message:
```
DEBUG Order handler: no onboarding session for sender=2348099887766 — continuing
INFO  Order handler: customer message sender=2348099887766 event_id=...
INFO  Order summary shown to customer order_id=<UUID> customer=2348099887766 total=80000
```

For Claude NLP Layer 2 being called:
```
INFO  Order handler: customer message sender=2348099887766 event_id=...
# (no Layer 2 specific log — look for the summary log appearing after a slight delay)
INFO  Order summary shown to customer ...
```

For a trader command:
```
INFO  Order handler: trader command sender=2348012345678 event_id=...
INFO  Order transition order_id=<UUID> inquiry -> confirmed
INFO  Trader confirmed order_id=<UUID> ref=3f8a2c1b
```

For a duplicated message being dropped:
```
INFO  Duplicate message dropped event_id=... conversation_id=...
```

For the onboarding skip:
```
DEBUG Order handler: sender=2348055551234 is in onboarding — skipping event_id=...
```

For a reply send failure (WhatsApp credentials missing or expired):
```
ERROR Order reply failed phone=2348099887766 event_id=order.summary.<UUID>: ...
```

### Warning signs that indicate a problem

| Log message | Probable cause |
|---|---|
| `Order handler: no completed trader for tenant=...` | No Trader row with that tenant_id and status=complete |
| `Claude NLP failed: ...` | ANTHROPIC_API_KEY not set or invalid |
| `Audio transcription failed media_id=...` | OPENAI_API_KEY not set, or media_id is stale (Meta media URLs expire) |
| `Order reply failed phone=... event_id=...` | WhatsApp channel credentials missing or token expired |
| `Notification already sent for event_id=...` | Duplicate message — normal, expected behaviour |
| `Order transition inquiry -> confirmed ... not allowed` | Order is already in a terminal state |
| `Duplicate message dropped` | Same message_id received twice — expected deduplication |

---

## 16. Common Failures and Fixes

| Symptom | Check | Fix |
|---|---|---|
| No order created after customer message | Logs: `no completed trader for tenant` | Insert a completed Trader row with the correct tenant_id |
| Customer gets no WhatsApp reply | Logs: `Order reply failed` | Set WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN; register channel via API |
| Trader identity not detected | Logs: `customer message sender=<trader_phone>` | Verify Trader.phone_number matches exactly (no `+` prefix, E.164) |
| Claude not called for complex messages | Logs: Claude NLP warning | Set ANTHROPIC_API_KEY |
| Voice note not transcribed | Logs: `Audio transcription failed` | Set OPENAI_API_KEY; use a real Meta media_id (mock media_ids are rejected by Meta) |
| `CONFIRM <ref>` not recognised | Trader gets command guide | Verify ref is exactly 6–16 lowercase hex chars; check the order is in INQUIRY state |
| Onboarding handler and order handler both process the same message | Log: both handlers log for same event_id | Verify `get_state(phone)` check in order handler is present; clear stale Redis onboarding keys |
| Two orders created for one customer message | Logs: duplicate `Order summary shown` | Clear the idempotency cache; check the message_id is unique per message |
| `order.state_changed` event published but order not in DB | Commit happened but session closed prematurely | Check `await self._db.commit()` is called before `_reply()` in service.py |
