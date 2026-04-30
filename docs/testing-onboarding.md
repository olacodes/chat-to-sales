# Trader Onboarding: End-to-End Walkthrough

This guide follows a real trader — **Mama Caro** — through the complete ChatToSales
onboarding journey. It covers both phases:

- **Phase 1** — Mama Caro messages the platform WhatsApp number, completes the onboarding
  bot, and her store goes live. Customers can immediately order by messaging the platform
  number.
- **Phase 2** — Mama Caro logs into the dashboard, connects her own WhatsApp Business
  number, and her store page automatically switches to route orders directly to her.

Every step can be tested without a real phone using the API simulation commands provided.

---

## Contents

1. [How the system works](#1-how-the-system-works)
2. [Prerequisites](#2-prerequisites)
3. [Starting the stack](#3-starting-the-stack)
4. [Phase 1 — WhatsApp Bot Onboarding](#4-phase-1--whatsapp-bot-onboarding)
   - [Act 1: Mama Caro sends her first message](#act-1-mama-caro-sends-her-first-message)
   - [Act 2: The onboarding conversation — four paths](#act-2-the-onboarding-conversation--four-paths)
     - [Path D — Skip (fastest)](#path-d--skip-fastest)
     - [Path C — Q&A questions](#path-c--qa-questions)
     - [Path A — Photo / OCR](#path-a--photo--ocr)
     - [Path B — Voice note / Whisper](#path-b--voice-note--whisper)
   - [Act 3: Store is live, customers can order](#act-3-store-is-live-customers-can-order)
5. [Phase 2 — Connecting Her Own WhatsApp Number](#5-phase-2--connecting-her-own-whatsapp-number)
   - [Act 4: Dashboard connect banner](#act-4-dashboard-connect-banner)
   - [Act 5: Meta Embedded Signup in Settings](#act-5-meta-embedded-signup-in-settings)
   - [Act 6: Store page automatically switches](#act-6-store-page-automatically-switches)
6. [Edge case tests](#6-edge-case-tests)
7. [Verifying state in Redis](#7-verifying-state-in-redis)
8. [Verifying the Trader row in PostgreSQL](#8-verifying-the-trader-row-in-postgresql)
9. [Resetting a trader for re-testing](#9-resetting-a-trader-for-re-testing)
10. [What to check in the logs](#10-what-to-check-in-the-logs)
11. [Common failures and fixes](#11-common-failures-and-fixes)

---

## 1. How the system works

### Message flow

```
Mama Caro (WhatsApp) or curl simulation
          |
          v
POST /api/v1/webhooks/webhook       <- internal normalised endpoint
          or
POST /api/v1/webhooks/whatsapp      <- raw Meta Cloud API webhook
          |
          v
IngestionService.process()
          |  publishes -> message.received (Redis pub/sub)
          v
ConversationService.handle_inbound()   <- persists message to DB
          |  publishes -> conversation.message_saved (Redis pub/sub)
          v
OnboardingService.handle()             <- drives the state machine
          |  state stored in: onboarding:state:{phone}  (Redis)
          |  on completion   -> writes Trader row to PostgreSQL
          v
NotificationService.send_message()     <- sends WhatsApp reply via Meta API
```

The pipeline is async and event-driven. After you send a message via curl, allow
1–2 seconds before inspecting Redis or PostgreSQL.

### The trigger keyword guard

The onboarding handler only activates for a phone number with no prior state when
the first message is a known trigger word. This prevents customers ordering from
Mama Caro's store from accidentally entering the trader onboarding flow.

Trigger words: `start`, `register`, `join`, `hi`, `hello`, `hey` (case-insensitive).

Any other first message from an unknown number is silently ignored by the onboarding
handler and routed only to the conversation service. If the onboarding handler did
respond, it would send:

> "Hi! To get started as a trader on ChatToSales, send *START* and I go guide you."

---

## 2. Prerequisites

### 2a. Environment variables

```bash
cp .env.example .env
```

Minimum required for all tests:

```env
# App
TENANT_ID=tenant-test-001
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/chattosales
REDIS_URL=redis://localhost:6379/0

# WhatsApp (required for replies to actually be delivered)
WHATSAPP_VERIFY_TOKEN=mytoken
WHATSAPP_APP_SECRET=           # leave empty to skip signature check locally
WHATSAPP_PHONE_NUMBER_ID=      # your Meta phone number ID
WHATSAPP_ACCESS_TOKEN=         # your Meta access token

# Phase 1 ordering — the platform's own WhatsApp number (E.164, no +)
PLATFORM_WHATSAPP_NUMBER=      # e.g. 15551234567

# Phase 2 — Meta app credentials for Embedded Signup code exchange
META_APP_ID=                   # your Meta App ID
WHATSAPP_APP_SECRET=           # same secret used above
```

For Path A (OCR) and Path B (voice transcription):

```env
GOOGLE_VISION_API_KEY=...      # Google Cloud Console -> APIs -> Vision API
OPENAI_API_KEY=sk-...          # for Whisper transcription
ANTHROPIC_API_KEY=sk-ant-...   # for Claude product extraction
```

If you leave AI keys empty, Paths A and B fall back gracefully — the bot sends the
"I no fit read this" fallback and the trader can choose a different path.

### 2b. Register the WhatsApp channel for your tenant

Replies are sent via credentials stored in `tenant_channels`. Register them once:

```bash
curl -s -X POST http://localhost:8000/api/v1/channels/whatsapp/connect \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "tenant-test-001",
    "phone_number_id": "YOUR_PHONE_NUMBER_ID",
    "access_token": "YOUR_ACCESS_TOKEN"
  }'
```

Expected: `{"status": "connected", ...}`.

If you skip this, all bot replies will fail with `NotFoundError` and you will see
"Onboarding reply failed" in the logs. State transitions will still work correctly.

---

## 3. Starting the stack

### Option A — Docker (recommended)

```bash
docker compose up --build
```

Starts: FastAPI on `:8000`, PostgreSQL on `:5432`, Redis on `:6379`.

### Option B — Local venv

```bash
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

PostgreSQL and Redis must be running separately.

### Verify the server is up

```bash
curl http://localhost:8000/health
```

Expected:
```json
{"status": "ok", "app": "ChatToSales", "version": "0.1.0", "environment": "development"}
```

---

## 4. Phase 1 — WhatsApp Bot Onboarding

### Act 1: Mama Caro sends her first message

Mama Caro heard about ChatToSales from a friend. She saves the platform WhatsApp
number and sends "Hi".

Because `hi` is a trigger keyword and her phone number has no prior onboarding state,
the onboarding handler activates and greets her.

**What she sends:** `Hi`

**What she receives:**

> "Eku ise! Welcome to ChatToSales. I dey here to help you set up your business so
> your customers fit order from you direct on WhatsApp. Wetin be your business name?"

```bash
# Simulation
PHONE=2348011111111

curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "'$PHONE'",
    "message": "Hi",
    "tenant_id": "tenant-test-001"
  }'
```

Wait ~2 seconds, then check the logs for `Notification sent ... event_id=onboarding_reply`.

**Redis state after this step:**

```json
{"step": "awaiting_name", "data": {"_last_active": 1714050123.0}}
```

---

### Act 2: The onboarding conversation — four paths

After Mama Caro provides her business name and category, she is offered four ways to
set up her price list. The steps below cover all four paths independently.

---

#### Path D — Skip (fastest)

**Use this path first.** It completes onboarding in 4 messages with no price list.
Mama Caro can add prices later as orders come in.

**Phone:** `2348011111111`

| Step | Mama Caro sends    | Bot responds                                                                          |
|------|--------------------|---------------------------------------------------------------------------------------|
| 1    | `Hi`               | Welcome message. Asks for business name.                                              |
| 2    | `Mama Caro Provisions` | "Mama Caro Provisions — I like am! Fire!" + category menu (1–7).                  |
| 3    | `1`                | "Provisions! Good choice. I don load 30 common items as a starting point." + catalogue path menu (1–4). |
| 4    | `4`                | Completion message with store link + command guide.                                   |

```bash
PHONE=2348011111111
BASE="http://localhost:8000/api/v1/webhooks/webhook"

curl -s -X POST $BASE -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"Hi","tenant_id":"tenant-test-001"}'

sleep 2

curl -s -X POST $BASE -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"Mama Caro Provisions","tenant_id":"tenant-test-001"}'

sleep 1

curl -s -X POST $BASE -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"1","tenant_id":"tenant-test-001"}'

sleep 1

curl -s -X POST $BASE -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"4","tenant_id":"tenant-test-001"}'
```

**Verify after completion:**

- `traders` row exists: `store_slug = mama-caro-provisions`, `onboarding_status = complete`
- `onboarding_catalogue` = `NULL` (nothing collected — expected for Path D)
- Redis key `onboarding:state:2348011111111` no longer exists

---

#### Path C — Q&A questions

Mama Caro answers questions one item at a time. She can skip at any point.

**Phone:** `2348022222222`

| Step | Mama Caro sends   | Bot responds                                           |
|------|-------------------|--------------------------------------------------------|
| 1    | `Hello`           | Welcome message.                                       |
| 2    | `Iya Taiwo Fabrics` | Category menu.                                       |
| 3    | `2`               | "Fabric! Good choice." + path menu.                    |
| 4    | `3`               | First Q&A: "Plain Ankara (per yard) — wetin be your price?" |
| 5    | `3500`            | Next question: "Printed Ankara (per yard)..."          |
| 6    | `4200`            | Next question.                                         |
| 7    | `skip`            | "No problem, we go skip the rest." + completion message. |

After the 5th answer (in a separate run without `skip`), she receives a checkpoint:

> "Good progress! 5 of 30 done. Keep going — type *skip* anytime to jump to the end."

**Price format variations — all of these must be accepted:**

| Input   | Parsed price |
|---------|--------------|
| `3500`  | 3500         |
| `3,500` | 3500         |
| `N3500` | 3500         |
| `₦3,500`| 3500         |
| `3.5k`  | 3500         |

**Verify:** `onboarding_catalogue` contains only the items answered before `skip`.

---

#### Path A — Photo / OCR

Mama Caro photographs her handwritten price list. The bot reads it with Google Vision
and extracts products with Claude.

**Requires:** `GOOGLE_VISION_API_KEY` and `ANTHROPIC_API_KEY` in `.env`.

**Phone:** `2348033333333`

| Step | Mama Caro sends         | Bot responds                                      |
|------|-------------------------|---------------------------------------------------|
| 1    | `Hello`                 | Welcome message.                                  |
| 2    | `Mama Gold Wholesale`   | Category menu.                                    |
| 3    | `1`                     | Confirmation + path menu.                         |
| 4    | `1`                     | "Oya! Send me the photo of your price list now."  |
| 5    | (photo of price list)   | "Reading your price list... (give me small time)" then numbered product list. |
| 6    | `YES`                   | "Done! All X items added." + completion message.  |

**Step 6 variation — correction:**

```
yes but number 2 na Rice 50kg = 63000
```

Expected: "Fixed! All X items added." + completion message. Verify the corrected price
appears in `onboarding_catalogue` in PostgreSQL.

**Fallback (no API key or unreadable photo):**

> "Hmm, I no fit read this photo well enough. No wahala! Choose another way:
> 3 - Answer small small questions with me
> 4 - Skip for now, I go learn as orders come in"

Trader returns to `AWAITING_CATALOGUE`. No data is lost.

**API simulation (requires a real Meta media_id for the download to succeed):**

```bash
PHONE=2348033333333

# Steps 1-4
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"Hello","tenant_id":"tenant-test-001"}'
sleep 2

curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"Mama Gold Wholesale","tenant_id":"tenant-test-001"}'
sleep 1

curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"1","tenant_id":"tenant-test-001"}'
sleep 1

curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"1","tenant_id":"tenant-test-001"}'
sleep 1

# Step 5: simulate image
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "'$PHONE'",
    "message": "[image]",
    "tenant_id": "tenant-test-001",
    "media_id": "REAL_MEDIA_ID",
    "media_type": "image/jpeg"
  }'
sleep 5

# Step 6: confirm
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"YES","tenant_id":"tenant-test-001"}'
```

---

#### Path B — Voice note / Whisper

Mama Caro records a voice note listing her prices. Whisper transcribes it and Claude
extracts the product-price pairs.

**Requires:** `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` in `.env`.

**Phone:** `2348044444444`

| Step | Mama Caro sends         | Bot responds                                           |
|------|-------------------------|--------------------------------------------------------|
| 1    | `Hello`                 | Welcome message.                                       |
| 2    | `Fresh Food by Adunola` | Category menu.                                         |
| 3    | `3`                     | Confirmation + path menu.                              |
| 4    | `2`                     | "Oya! Record voice note and list your products with prices." |
| 5    | (voice note)            | "I don receive your voice note, transcribing now..." then product list. |
| 6    | `YES`                   | "Done! All X items added." + completion message.       |

**Voice note content that works well:**

> "Good morning! My prices: Jollof rice per plate na one thousand five hundred naira,
> fried rice per plate na the same, pounded yam na twelve hundred, egusi soup per
> serving na two thousand, pepper soup na one thousand eight hundred. Thank you."

Whisper uses a Nigerian English prompt. Claude extracts the pairs.

**Fallback** (silent audio or missing `OPENAI_API_KEY`):

> "I no fit hear the voice note well enough. No wahala! Choose another way:
> 3 - Answer small small questions with me
> 4 - Skip for now, I go learn as orders come in"

---

### Act 3: Store is live, customers can order

When onboarding completes, Mama Caro receives her store link:

> Your store is live! Share this link with your customers:
> `https://chattosales.ng/store/mama-caro-provisions`

Visiting that URL shows her business name, category, and price list (if any). At the
top is an **"Order on WhatsApp"** button.

**Phase 1 behaviour (no own number connected):**

The button URL is built like this:

```
https://wa.me/PLATFORM_WHATSAPP_NUMBER?text=I%20want%20to%20order%20from%20Mama%20Caro%20Provisions
```

When a customer taps it, WhatsApp opens pre-loaded with the message
"I want to order from Mama Caro Provisions" addressed to the platform number. The order
handler on the platform number detects the order intent and creates an inquiry.

**Confirming Phase 1 ordering URL via the store API:**

```bash
curl -s http://localhost:8000/api/v1/store/mama-caro-provisions | python3 -m json.tool
```

Expected:
```json
{
  "business_name": "Mama Caro Provisions",
  "business_category": "provisions",
  "store_slug": "mama-caro-provisions",
  "ordering_whatsapp_url": "https://wa.me/15551234567?text=I%20want%20to%20order%20from%20Mama%20Caro%20Provisions",
  "catalogue": []
}
```

---

## 5. Phase 2 — Connecting Her Own WhatsApp Number

A few days after onboarding, Mama Caro logs into the ChatToSales web dashboard at
`https://chattosales.ng/login`. She registers and is taken to the dashboard.

### Act 4: Dashboard connect banner

At the top of the dashboard she sees a yellow banner:

> **Connect your WhatsApp number** — Let customers order directly from your own
> WhatsApp number instead of the platform number.
> [Connect ->]

The banner is shown when the tenant has no channel connected. Clicking "Connect" takes
her to `/settings`.

**Testing this in the UI:**

1. Open the dashboard as a logged-in trader whose tenant has no entry in `tenant_channels`.
2. The yellow connect banner should appear above the main stats.
3. Clicking "Connect" navigates to `/settings`.

To confirm no channel exists for a tenant:

```bash
docker compose exec postgres psql -U postgres -d chattosales \
  -c "SELECT * FROM tenant_channels WHERE tenant_id = 'tenant-test-001';"
# Should return zero rows before Phase 2
```

---

### Act 5: Meta Embedded Signup in Settings

In Settings, Mama Caro sees the **Channels** section with a "Connect WhatsApp" button.
Clicking it opens the Meta Embedded Signup popup.

**What happens under the hood:**

1. The frontend loads the Meta JavaScript SDK (`https://connect.facebook.net/en_US/sdk.js`).
2. The `FB.login()` call opens the Meta popup.
3. Mama Caro follows the steps: logs into her Facebook account, selects her WhatsApp
   Business Account (WABA), and grants permissions.
4. On success, Meta returns a short-lived `code` (30-second TTL), `phone_number_id`,
   and `waba_id` to the frontend.
5. The frontend immediately calls `POST /api/v1/channels/whatsapp/embedded-signup` with
   all three values.
6. The backend exchanges the `code` for an `access_token` via the Meta Graph API, then
   stores the credentials in `tenant_channels`.

**Testing the backend endpoint directly (simulating a successful popup):**

```bash
# This requires a real, live code from Meta (30s TTL) — test in the UI, not curl
curl -s -X POST http://localhost:8000/api/v1/channels/whatsapp/embedded-signup \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "tenant-test-001",
    "code": "REAL_LIVE_CODE_FROM_META_POPUP",
    "phone_number_id": "123456789012345",
    "waba_id": "987654321098765"
  }'
```

Expected:
```json
{
  "status": "connected",
  "channel": "whatsapp",
  "phone_number_id": "123456789012345",
  "webhook_registered": false
}
```

**Confirm the channel row was created:**

```bash
docker compose exec postgres psql -U postgres -d chattosales \
  -c "SELECT tenant_id, channel, phone_number_id, webhook_registered FROM tenant_channels;"
```

**Alternative — insert a channel row manually to test the store switch without a real code:**

```bash
curl -s -X POST http://localhost:8000/api/v1/channels/whatsapp/connect \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "tenant-test-001",
    "phone_number_id": "123456789012345",
    "access_token": "FAKE_TOKEN_FOR_LOCAL_TESTING"
  }'
```

---

### Act 6: Store page automatically switches

As soon as `tenant_channels` has a row for Mama Caro's tenant, the store page at
`/store/mama-caro-provisions` automatically starts returning her own number in the
`ordering_whatsapp_url`.

**Confirm the switch:**

```bash
curl -s http://localhost:8000/api/v1/store/mama-caro-provisions | python3 -m json.tool
```

Expected (Phase 2 — own number connected):
```json
{
  "business_name": "Mama Caro Provisions",
  "business_category": "provisions",
  "store_slug": "mama-caro-provisions",
  "ordering_whatsapp_url": "https://wa.me/2348112345678",
  "catalogue": []
}
```

The URL is now Mama Caro's own number — no `?text=` prefix — so WhatsApp opens a
direct conversation with her business, not the platform number.

The dashboard banner also disappears once the channel is connected.

---

## 6. Edge case tests

### Edge case 1 — Customer message does not trigger onboarding

A customer sends a non-trigger message to the platform number. The onboarding handler
must ignore it.

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2349066171234",
    "message": "I want 2 cartons of indomie",
    "tenant_id": "tenant-test-001"
  }'
```

Expected:
- Onboarding service logs nothing for this phone number (no state, non-trigger word).
- Order handler creates an inquiry order.
- No onboarding welcome message is sent to the customer.

If the customer then sends `hi` on a separate message, **that** will trigger onboarding
(since they have no prior state). This is the correct behaviour — a customer who
accidentally sends "hi" will get a polite prompt to send `START` to start as a trader.

---

### Edge case 2 — Business name too short

```bash
PHONE=2348055555551

curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"Hello","tenant_id":"tenant-test-001"}'

sleep 2

curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"A","tenant_id":"tenant-test-001"}'
```

Expected: "Hmm, that name dey too short o! Abeg type your full business name (at least 2 letters)."

State stays at `AWAITING_NAME`. Send a valid name and the flow continues normally.

---

### Edge case 3 — Category "other" (option 7)

Go through steps 1–2 normally, then send `7` for category.

Expected: "Got it! Abeg tell me brief brief wetin you sell."

Send a description:

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"2348055555552","message":"I sell children school uniforms and bags","tenant_id":"tenant-test-001"}'
```

Expected: Catalogue path menu appears. In PostgreSQL after completion:
`business_category = "I sell children school uniforms and bags"`.

---

### Edge case 4 — Welcome back (abandoned session)

Test that a trader who started onboarding hours ago gets a warm welcome back.

```bash
PHONE=2348055555553

# Start onboarding
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"Hello","tenant_id":"tenant-test-001"}'

sleep 2

# Manually set _last_active to 7 hours ago
docker compose exec redis redis-cli \
  SET "onboarding:state:$PHONE" \
  '{"step":"awaiting_name","data":{"_last_active":1714024800.0}}' \
  EX 604800

# Send next message — bot should greet her back before continuing
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"Mama Emeka Stores","tenant_id":"tenant-test-001"}'
```

Expected: Bot first sends "Welcome back! You were setting up your store — make we
continue from where we stop!", then continues with the category menu.

---

### Edge case 5 — Slug collision

Two traders with the same business name must get distinct slugs.

1. Complete onboarding for phone `2348055555554` with name `Mama Caro Provisions`.
2. Reset: `DELETE FROM traders WHERE phone_number = '2348055555554';` — do **not**
   delete the original Mama Caro row.
3. Complete onboarding for phone `2348055555555` with the same name.

In PostgreSQL:
- Trader 1: `store_slug = mama-caro-provisions`
- Trader 2: `store_slug = mama-caro-provisions-2`

---

### Edge case 6 — Already onboarded trader messages again

After completing onboarding, the same phone number sends another message:

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"2348011111111","message":"Hello again","tenant_id":"tenant-test-001"}'
```

Expected: Onboarding service finds the existing `Trader` row and exits silently. The
message is handled only by the conversation service. No onboarding message is sent.

---

### Edge case 7 — Invalid catalogue path choice

When at the catalogue path menu, send an invalid option:

Expected: "Abeg reply with 1, 2, 3, or 4." State stays at `AWAITING_CATALOGUE`.

---

### Edge case 8 — Sending text while waiting for a photo (Path A)

After selecting option `1` (photo path), send text instead of an image.

Expected: "I dey wait for photo o — abeg send photo or type *3* to answer questions instead."

State stays at `AWAITING_PHOTO`.

---

### Edge case 9 — Sending text while waiting for a voice note (Path B)

After selecting option `2` (voice path), send text instead of audio.

Expected: "I dey wait for voice note o — abeg send voice note or type *3* to answer questions instead."

State stays at `AWAITING_VOICE`.

---

## 7. Verifying state in Redis

Inspect the onboarding state at any mid-conversation point:

```bash
docker compose exec redis redis-cli
```

```redis
GET onboarding:state:2348011111111
```

Example mid-Q&A state:

```json
{
  "step": "qa_in_progress",
  "data": {
    "name": "Mama Caro Provisions",
    "category": "provisions",
    "qa_index": 3,
    "qa_prices": {
      "Indomie Carton": 8500,
      "Rice 50kg (Mama Gold)": 63000,
      "Peak Milk 400g": 1900
    },
    "_last_active": 1714050123.456
  }
}
```

After completion, the key must not exist:

```redis
EXISTS onboarding:state:2348011111111
# Returns: (integer) 0
```

---

## 8. Verifying the Trader row in PostgreSQL

```bash
docker compose exec postgres psql -U postgres -d chattosales
```

```sql
SELECT phone_number, business_name, business_category, store_slug,
       onboarding_status, tenant_id, tier,
       LEFT(onboarding_catalogue::text, 100) AS catalogue_preview
FROM traders
ORDER BY created_at DESC
LIMIT 10;
```

Expected after successful onboarding:

| Column              | Expected value               |
|---------------------|------------------------------|
| `phone_number`      | `2348011111111`              |
| `business_name`     | `Mama Caro Provisions`       |
| `business_category` | `provisions`                 |
| `store_slug`        | `mama-caro-provisions`       |
| `onboarding_status` | `complete`                   |
| `tier`              | `ofe`                        |
| `onboarding_catalogue` | `NULL` (Path D) or JSON  |

For Path C:

```sql
SELECT onboarding_catalogue FROM traders WHERE phone_number = '2348022222222';
```
```json
{"Plain Ankara (per yard)": 3500, "Printed Ankara (per yard)": 4200}
```

For Paths A or B:
```json
[{"name": "Indomie Carton", "price": 8500}, {"name": "Rice 50kg", "price": 63000}]
```

**Phase 2 — confirm channel was created:**

```sql
SELECT tenant_id, channel, phone_number_id, webhook_registered, created_at
FROM tenant_channels
WHERE tenant_id = 'tenant-test-001';
```

---

## 9. Resetting a trader for re-testing

To re-run onboarding for the same phone number from scratch:

```bash
# 1. Delete the Trader row
docker compose exec postgres psql -U postgres -d chattosales \
  -c "DELETE FROM traders WHERE phone_number = '2348011111111';"

# 2. Delete the Redis onboarding state
docker compose exec redis redis-cli DEL "onboarding:state:2348011111111"
```

To also remove the connected channel (reset to Phase 1):

```bash
docker compose exec postgres psql -U postgres -d chattosales \
  -c "DELETE FROM tenant_channels WHERE tenant_id = 'tenant-test-001';"
```

---

## 10. What to check in the logs

```bash
docker compose logs -f app
```

### Healthy onboarding flow

```
INFO  Published event=message.received tenant=tenant-test-001 ...
INFO  Message persisted conversation_id=... message_id=...
INFO  Published event=conversation.message_saved ...
INFO  Notification sent id=... recipient=234801... event_id=onboarding_reply...
```

On completion:

```
INFO  Onboarding complete phone=2348011111111 slug=mama-caro-provisions category=provisions
INFO  Notification sent ... event_id=onboarding_reply..._complete
```

### Customer message correctly ignored by onboarding

```
INFO  Message persisted conversation_id=... message_id=...
INFO  Published event=conversation.message_saved ...
# No "Notification sent ... event_id=onboarding_reply" line — correct
```

### Phase 2 — channel connection

```
INFO  WhatsApp channel connected tenant_id=tenant-test-001 phone_number_id=123456789012345
```

### Red flags

| Log message | What it means | Fix |
|---|---|---|
| `Onboarding reply failed phone=... NotFoundError` | Channel not registered | Run `/channels/whatsapp/connect` (section 2b) |
| `GOOGLE_VISION_API_KEY not set` | Missing key | Add to `.env` |
| `OPENAI_API_KEY not set` | Missing key | Add to `.env` |
| `ANTHROPIC_API_KEY not set` | Missing key | Add to `.env` |
| `OCR returned empty text` | Photo unreadable | Expected — fallback message sent |
| `Whisper returned empty transcript` | Audio inaudible | Expected — fallback message sent |
| `Meta code exchange returned no access_token` | Embedded Signup code expired | Code has 30s TTL; trigger signup again |
| `Already sent for event_id` | Duplicate event processed | Not an error — idempotency guard working |

---

## 11. Common failures and fixes

### Onboarding handler never fires

**Cause:** Redis pub/sub not connected.

```bash
docker compose exec redis redis-cli PING   # Should return: PONG
```

Look for `Subscribed to channel: chattosales.events.*` in the startup logs.

---

### State machine gets stuck on a step

**Cause:** Stale Redis state from a previous test.

**Fix:** Reset the trader (section 9).

---

### `conversation.message_saved` never published

**Cause:** Conversation service could not persist the message (DB unreachable).

```bash
docker compose exec postgres psql -U postgres -d chattosales \
  -c "SELECT COUNT(*) FROM messages;"
```

If this fails: `docker compose ps postgres` — check if the container is healthy.

---

### Store page still shows platform URL after connecting own number

**Cause:** Next.js ISR cache (`revalidate: 60`). The store page caches for 60 seconds.

**Fix:** Wait 60 seconds, or restart the dev server.

If running backend tests only (no Next.js), call the backend store endpoint directly:

```bash
curl -s http://localhost:8000/api/v1/store/mama-caro-provisions
```

The backend has no cache — it reads `tenant_channels` on every request.

---

### Replies are sent but not received on the real phone

**Cause:** WhatsApp access token expired or wrong `WHATSAPP_PHONE_NUMBER_ID`.

Look for:

```
WhatsApp API error status=401
```

**Fix:** Refresh the token in Meta Developer Console and re-run `/channels/whatsapp/connect`.

---

### Embedded Signup code expired (Phase 2)

**Cause:** The Meta Embedded Signup `code` has a 30-second TTL. The backend received
it too late.

Look for:

```
Meta code exchange returned no access_token
```

**Fix:** Trigger the Embedded Signup popup again and ensure the frontend calls
`POST /channels/whatsapp/embedded-signup` immediately after the popup closes.
