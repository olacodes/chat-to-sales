# Feature 1 — Smart Trader Onboarding: Testing Guide

This document covers everything required to test the Smart Trader Onboarding feature
end-to-end. It is structured so you can test without a live WhatsApp number (using the
internal API endpoint) and also test with a real phone.

---

## Contents

1. [How the system works (testing context)](#1-how-the-system-works-testing-context)
2. [Prerequisites](#2-prerequisites)
3. [Starting the stack](#3-starting-the-stack)
4. [Testing method A — API simulation (no real WhatsApp needed)](#4-testing-method-a--api-simulation-no-real-whatsapp-needed)
5. [Testing method B — Real WhatsApp end-to-end](#5-testing-method-b--real-whatsapp-end-to-end)
6. [Test scenario 1 — Path D: Skip (fastest happy path)](#6-test-scenario-1--path-d-skip)
7. [Test scenario 2 — Path C: Q&A](#7-test-scenario-2--path-c-qa)
8. [Test scenario 3 — Path A: Photo / OCR](#8-test-scenario-3--path-a-photo--ocr)
9. [Test scenario 4 — Path B: Voice note / Whisper](#9-test-scenario-4--path-b-voice-note--whisper)
10. [Edge case tests](#10-edge-case-tests)
11. [Verifying state in Redis](#11-verifying-state-in-redis)
12. [Verifying the Trader row in PostgreSQL](#12-verifying-the-trader-row-in-postgresql)
13. [Resetting a trader for re-testing](#13-resetting-a-trader-for-re-testing)
14. [What to check in the logs](#14-what-to-check-in-the-logs)
15. [Common failures and fixes](#15-common-failures-and-fixes)

---

## 1. How the system works (testing context)

Understanding the message flow is essential before testing:

```
You (curl / real WhatsApp)
        │
        ▼
POST /api/v1/webhooks/webhook   ← internal normalised endpoint
        or
POST /api/v1/webhooks/whatsapp  ← raw Meta Cloud API webhook
        │
        ▼
IngestionService.process()
        │  publishes → message.received (Redis pub/sub)
        ▼
ConversationService.handle_inbound()  ← persists message to DB
        │  publishes → conversation.message_saved (Redis pub/sub)
        ▼
OnboardingService.handle()  ← drives the state machine
        │  state stored in Redis key: onboarding:state:{phone}
        │  on completion → writes Trader row to PostgreSQL
        ▼
NotificationService.send_message()  ← sends WhatsApp reply via Meta API
```

**Important:** Because the pipeline is async (event-driven through Redis pub/sub),
there is a small delay (typically < 1 second) between sending a message and receiving
the bot reply. When testing via API, wait 1–2 seconds before checking the reply in logs.

---

## 2. Prerequisites

### 2a. Environment variables

Copy the example env file and fill in the required values:

```bash
cp .env.example .env   # or .env.docker if using Docker
```

Minimum required for all tests:

```env
# App
TENANT_ID=tenant-test-001
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/chattosales
REDIS_URL=redis://localhost:6379/0

# WhatsApp (required for replies to actually send)
WHATSAPP_VERIFY_TOKEN=mytoken
WHATSAPP_APP_SECRET=          # leave empty to skip signature check locally
WHATSAPP_PHONE_NUMBER_ID=     # your Meta phone number ID
WHATSAPP_ACCESS_TOKEN=        # your Meta access token
```

For Path A and Path B (OCR / Whisper / Claude extraction):

```env
GOOGLE_VISION_API_KEY=...     # Google Cloud Console → APIs → Vision API → Credentials
OPENAI_API_KEY=sk-...         # platform.openai.com → API Keys
ANTHROPIC_API_KEY=sk-ant-...  # console.anthropic.com → API Keys
```

> **Testing without AI keys:** If you leave these empty, Paths A and B will still work
> but will fall back gracefully — OCR/transcription returns empty, the bot sends the
> "I no fit read this" fallback message, and the trader is returned to the catalogue
> menu. You can test the full happy path for Paths A and B only with real API keys.

### 2b. WhatsApp channel must be registered

The bot sends replies via the `tenant_channels` table. Before testing, register the
channel for your tenant:

```bash
curl -s -X POST http://localhost:8000/api/v1/channels/whatsapp/connect \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "tenant-test-001",
    "phone_number_id": "YOUR_PHONE_NUMBER_ID",
    "access_token": "YOUR_ACCESS_TOKEN"
  }'
```

Expected response: `{"status": "connected"}` or similar.

If you skip this step, all replies will fail with a `NotFoundError` and you will see
"Onboarding reply failed" in the logs — but state transitions will still work correctly.

---

## 3. Starting the stack

### Option A — Docker (recommended)

```bash
docker compose up --build
```

Starts: FastAPI app on `:8000`, PostgreSQL on `:5432`, Redis on `:6379`.

### Option B — Local venv

```bash
# Terminal 1 — PostgreSQL and Redis must be running separately
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

### Verify the server is running

```bash
curl http://localhost:8000/health
```

Expected:
```json
{"status": "ok", "app": "ChatToSales", "version": "0.1.0", "environment": "development"}
```

---

## 4. Testing method A — API simulation (no real WhatsApp needed)

You can simulate any inbound WhatsApp message by posting to the internal webhook
endpoint. This is the fastest way to test every scenario without needing a phone.

### Base command

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348012345678",
    "message": "YOUR_MESSAGE_HERE",
    "tenant_id": "tenant-test-001"
  }'
```

- Change `sender_identifier` for each test trader (this is their "phone number").
- Change `message` to simulate each step of the conversation.
- The endpoint returns `202 Accepted` immediately. The bot reply is sent asynchronously.
- Watch the app logs (`docker compose logs -f app`) to see the full pipeline.

### Simulating a media message (image or audio)

```bash
# Simulate an image being sent
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348012345678",
    "message": "[image]",
    "tenant_id": "tenant-test-001",
    "media_id": "REAL_MEDIA_ID_FROM_META",
    "media_type": "image/jpeg"
  }'

# Simulate an audio message
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "whatsapp",
    "sender_identifier": "2348012345678",
    "message": "[audio]",
    "tenant_id": "tenant-test-001",
    "media_id": "REAL_MEDIA_ID_FROM_META",
    "media_type": "audio/ogg"
  }'
```

> **Note:** `media_id` must be a real Meta media object ID for the download to succeed.
> For local testing without a real media ID, the download will fail and the bot will
> send the fallback message. This is the expected behaviour.

---

## 5. Testing method B — Real WhatsApp end-to-end

### Setup

1. Your server must be reachable from the internet (use ngrok locally):
   ```bash
   ngrok http 8000
   # Copy the https URL, e.g. https://abc123.ngrok.io
   ```

2. In Meta Developer Console → WhatsApp → Configuration:
   - Webhook URL: `https://abc123.ngrok.io/api/v1/webhooks/whatsapp`
   - Verify Token: same as `WHATSAPP_VERIFY_TOKEN` in your `.env`
   - Subscribe to: `messages`

3. Save the webhook. Meta will call `GET /api/v1/webhooks/whatsapp?hub.mode=subscribe&...`
   and the server will verify it.

4. Send a real WhatsApp message to your registered phone number.

---

## 6. Test scenario 1 — Path D: Skip

**Purpose:** Verify the full happy path with zero catalogue setup. This is the fastest
end-to-end test and should always be run first.

**Phone to use:** `2348011111111`

### Steps

| Step | You send | Expected bot response |
|------|----------|-----------------------|
| 1 | Any message — "Hello", "Hi", "Eku ise" | Welcome message in Nigerian English. Asks for business name. |
| 2 | `Mama Caro Provisions` | "Mama Caro Provisions - I like am! 🔥" + category menu (1–7). |
| 3 | `1` | "Provisions! Good choice. 👍 I don load 30 common items for you as a starting point." + catalogue path menu (1–4). |
| 4 | `4` | Completion message with store link `https://chattosales.ng/mama-caro-provisions` and full command guide. |

### What to verify after step 4

- A `traders` row exists in PostgreSQL (see section 12).
- `store_slug` = `mama-caro-provisions`
- `onboarding_status` = `complete`
- `onboarding_catalogue` = `NULL` (nothing was collected — expected for Path D)
- Redis key `onboarding:state:2348011111111` no longer exists (cleared on completion).

### API simulation commands

```bash
PHONE=2348011111111
BASE="http://localhost:8000/api/v1/webhooks/webhook"
HEADERS='-H "Content-Type: application/json"'

# Step 1
curl -s -X POST $BASE -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"Hello","tenant_id":"tenant-test-001"}'

sleep 2   # wait for async pipeline

# Step 2
curl -s -X POST $BASE -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"Mama Caro Provisions","tenant_id":"tenant-test-001"}'

sleep 1

# Step 3
curl -s -X POST $BASE -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"1","tenant_id":"tenant-test-001"}'

sleep 1

# Step 4
curl -s -X POST $BASE -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"4","tenant_id":"tenant-test-001"}'
```

---

## 7. Test scenario 2 — Path C: Q&A

**Purpose:** Verify the Q&A flow, progress checkpoints, skip command, and price capture.

**Phone to use:** `2348022222222`

### Steps

| Step | You send | Expected bot response |
|------|----------|-----------------------|
| 1 | `Hello` | Welcome message. |
| 2 | `Iya Taiwo Fabrics` | Category menu. |
| 3 | `2` | "Fabric! Good choice. 👍 I don load 30 common items..." + path menu. |
| 4 | `3` | First Q&A question: "Plain Ankara (per yard) — wetin be your price?" |
| 5 | `3500` | Next question: "Printed Ankara (per yard)..." |
| 6 | `4200` | Next question. |
| 7 | `skip` | Skips remaining Q&A. Sends "No problem, we go skip the rest." → then completion message. |

### Checkpoint test (separate run)

Instead of `skip` at step 7, answer 5 consecutive questions with prices.
After the 5th answer you should receive:

> "Good progress! 5 of 30 done. Keep going — type *skip* anytime to jump to the end."

Then the 6th question is sent.

### Price format variations to test in Q&A

These should all be accepted:

| Input | Expected parsed price |
|-------|-----------------------|
| `3500` | 3500 |
| `3,500` | 3500 |
| `N3500` | 3500 |
| `₦3,500` | 3500 |
| `3.5k` | 3500 |

### What to verify after completion

- `traders` row exists with `business_category = fabric`
- `onboarding_catalogue` contains JSON: `{"Plain Ankara (per yard)": 3500, "Printed Ankara (per yard)": 4200, ...}`
- Only the items you answered (before `skip`) are in the catalogue.

---

## 8. Test scenario 3 — Path A: Photo / OCR

**Purpose:** Verify the photo → OCR → Claude extraction → confirmation → completion flow.

**Requires:** `GOOGLE_VISION_API_KEY` and `ANTHROPIC_API_KEY` set in `.env`.

**Phone to use:** `2348033333333`

### Steps

| Step | You send | Expected bot response |
|------|----------|-----------------------|
| 1 | `Hello` | Welcome message. |
| 2 | `Mama Gold Wholesale` | Category menu. |
| 3 | `1` | Confirmation + path menu. |
| 4 | `1` | "Oya! Send me the photo of your price list now." |
| 5 | Send a photo of a handwritten or printed price list | "Reading your price list now... (give me small time ⏳)" then a numbered list of extracted products. |
| 6 | `YES` | "Done! All X items added to your store. ✅" then completion message. |

### Step 6 variation — Correction

Instead of `YES` at step 6, send:

```
yes but number 2 na Rice 50kg = 63000
```

Expected response: "Fixed! All X items added to your store. ✅" + completion message.

Verify in PostgreSQL that the corrected price (63000) appears in `onboarding_catalogue`.

### Testing Path A fallback (no API key or unreadable photo)

With `GOOGLE_VISION_API_KEY` left empty **or** by sending an image that is completely
black/blank:

Expected: The bot sends:

> "Hmm, I no fit read this photo well enough. No wahala! Choose another way:
> 3 - Answer small small questions with me
> 4 - Skip for now, I go learn as orders come in"

The trader is returned to the `AWAITING_CATALOGUE` step and can choose a different path.

### API simulation for Path A (with a real media_id)

```bash
PHONE=2348033333333

# Steps 1-4: same as Path D but send "1" at step 4
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

# Step 5: simulate image sent (replace REAL_MEDIA_ID with a live media object ID from Meta)
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel":"whatsapp",
    "sender_identifier":"'$PHONE'",
    "message":"[image]",
    "tenant_id":"tenant-test-001",
    "media_id":"REAL_MEDIA_ID",
    "media_type":"image/jpeg"
  }'

sleep 5   # OCR + Claude takes a few seconds

# Step 6: confirm
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"YES","tenant_id":"tenant-test-001"}'
```

---

## 9. Test scenario 4 — Path B: Voice note / Whisper

**Purpose:** Verify the audio → Whisper transcription → Claude extraction → confirmation → completion flow.

**Requires:** `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` set in `.env`.

**Phone to use:** `2348044444444`

### Steps

| Step | You send | Expected bot response |
|------|----------|-----------------------|
| 1 | `Hello` | Welcome message. |
| 2 | `Fresh Food by Adunola` | Category menu. |
| 3 | `3` | Confirmation + path menu. |
| 4 | `2` | "Oya! Record voice note and list your products with their prices." |
| 5 | Send a voice note (e.g. "Jollof rice na 1500 per plate, fried rice na 1500, pounded yam na 1200 per plate") | "I don receive your voice note, transcribing now... (give me small time ⏳)" then the product list. |
| 6 | `YES` | "Done! All X items added to your store. ✅" then completion message. |

### Voice note content guide for testing

Record a voice note saying something like:

> "Good morning! My prices: Jollof rice per plate na one thousand five hundred naira,
> fried rice per plate na the same, pounded yam na twelve hundred, egusi soup per
> serving na two thousand, pepper soup na one thousand eight hundred. Thank you."

The Whisper model is configured with a Nigerian English prompt so it should transcribe
this accurately. Claude then extracts the product-price pairs.

### Testing Path B fallback

Record a completely silent audio, or use `OPENAI_API_KEY=` (empty). The bot should
respond:

> "I no fit hear the voice note well enough. No wahala! Choose another way:
> 3 - Answer small small questions with me
> 4 - Skip for now, I go learn as orders come in"

### API simulation for Path B

```bash
PHONE=2348044444444

# Steps 1-4 (same pattern, send "2" at step 4 instead of "1")
# ... then:

# Step 5: simulate audio sent
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "channel":"whatsapp",
    "sender_identifier":"'$PHONE'",
    "message":"[audio]",
    "tenant_id":"tenant-test-001",
    "media_id":"REAL_MEDIA_ID",
    "media_type":"audio/ogg"
  }'
```

---

## 10. Edge case tests

### Edge case 1 — Business name too short

**Phone:** `2348055555551`

```bash
# Step 1: first message
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"2348055555551","message":"Hello","tenant_id":"tenant-test-001"}'

sleep 2

# Step 2: send a single character as a name
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"2348055555551","message":"A","tenant_id":"tenant-test-001"}'
```

Expected: "Hmm, that name dey too short o! Abeg type your full business name (at least 2 letters)."

State stays at `AWAITING_NAME`. Next, send a valid name and the flow continues.

---

### Edge case 2 — Category "other" (option 7)

**Phone:** `2348055555552`

Go through steps 1–2 normally, then:

```bash
# Step 3: select category 7
curl ... -d '{"message":"7",...}'
```

Expected: "Got it! Abeg tell me brief brief wetin you sell."

Then send a description:

```bash
curl ... -d '{"message":"I sell children school uniforms and bags","...}'
```

Expected: Catalogue path menu appears. Select "4" (skip) and verify completion.

In PostgreSQL: `business_category` = `"I sell children school uniforms and bags"` (the free-text description).

---

### Edge case 3 — Welcome back (abandoned session)

This test requires manipulating Redis directly to set an old `_last_active` timestamp.

```bash
# Start onboarding for a new phone
PHONE=2348055555553
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"Hello","tenant_id":"tenant-test-001"}'

sleep 2

# Now manually set _last_active to 7 hours ago in Redis
docker compose exec redis redis-cli
```

Inside the Redis CLI:

```redis
GET onboarding:state:2348055555553
```

You'll see JSON like `{"step": "awaiting_name", "data": {"_last_active": 1714000000.0}}`.

Set `_last_active` to a timestamp 7 hours in the past:

```redis
# Get current Unix timestamp and subtract 25200 (7 hours in seconds)
# Example: if now is 1714050000, use 1714050000 - 25200 = 1714024800
SET onboarding:state:2348055555553 '{"step":"awaiting_name","data":{"_last_active":1714024800.0}}'
EX 604800
```

Then send another message:

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"'$PHONE'","message":"Mama Emeka Stores","tenant_id":"tenant-test-001"}'
```

Expected: Bot first sends "Welcome back! You were setting up your store — make we continue from where we stop! 👋", then immediately continues with the category menu.

---

### Edge case 4 — Slug collision

**Purpose:** Verify that if `mama-caro-provisions` already exists, the second trader gets `mama-caro-provisions-2`.

1. Complete a full onboarding for phone `2348055555554` with business name `Mama Caro Provisions`.
2. Complete another full onboarding for phone `2348055555555` with the same business name `Mama Caro Provisions`.

In PostgreSQL, verify:
- Trader 1: `store_slug = mama-caro-provisions`
- Trader 2: `store_slug = mama-caro-provisions-2`

---

### Edge case 5 — Already onboarded trader messages again

After completing onboarding for any phone number, send another message with the same phone:

```bash
curl -s -X POST http://localhost:8000/api/v1/webhooks/webhook \
  -H "Content-Type: application/json" \
  -d '{"channel":"whatsapp","sender_identifier":"2348011111111","message":"Hello again","tenant_id":"tenant-test-001"}'
```

Expected: The onboarding service silently exits (finds the existing `Trader` row and returns immediately). The message is routed only to the conversation service. No onboarding messages are sent.

---

### Edge case 6 — Invalid catalogue path choice

When at the catalogue path menu, send an invalid option:

```bash
curl ... -d '{"message":"5",...}'   # 5 is not a valid option
```

Expected: "Abeg reply with 1, 2, 3, or 4."

State stays at `AWAITING_CATALOGUE`.

---

### Edge case 7 — Sending text while waiting for a photo (Path A)

After choosing option "1" (photo path), send text instead of an image:

```bash
curl ... -d '{"message":"here is my price list","...}'
```

Expected: "I dey wait for photo o — abeg send photo or type *3* to answer questions instead."

State stays at `AWAITING_PHOTO`.

---

### Edge case 8 — Sending text while waiting for a voice note (Path B)

After choosing option "2" (voice path), send text instead of audio:

```bash
curl ... -d '{"message":"jollof rice 1500 fried rice 1500","...}'
```

Expected: "I dey wait for voice note o — abeg send voice note or type *3* to answer questions instead."

State stays at `AWAITING_VOICE`.

---

## 11. Verifying state in Redis

At any point mid-onboarding, inspect the Redis state:

```bash
docker compose exec redis redis-cli
```

```redis
# Check what step the trader is on
GET onboarding:state:2348011111111
```

Expected output (example — mid Q&A):

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

After completion, the key should not exist:

```redis
EXISTS onboarding:state:2348011111111
# Returns: (integer) 0
```

---

## 12. Verifying the Trader row in PostgreSQL

```bash
docker compose exec postgres psql -U postgres -d chattosales
```

```sql
-- See all onboarded traders
SELECT phone_number, business_name, business_category, store_slug,
       onboarding_status, tier, LEFT(onboarding_catalogue, 100) AS catalogue_preview
FROM traders
ORDER BY created_at DESC
LIMIT 10;
```

Expected columns after a successful onboarding:

| Column | Expected value |
|--------|---------------|
| `phone_number` | `2348011111111` |
| `business_name` | `Mama Caro Provisions` |
| `business_category` | `provisions` |
| `store_slug` | `mama-caro-provisions` |
| `onboarding_status` | `complete` |
| `tier` | `ofe` |
| `onboarding_catalogue` | `NULL` (Path D) or JSON string (Paths A/B/C) |

For Path C, the catalogue JSON should look like:
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

---

## 13. Resetting a trader for re-testing

To re-run onboarding for the same phone number:

```bash
# 1. Delete the Trader row from PostgreSQL
docker compose exec postgres psql -U postgres -d chattosales \
  -c "DELETE FROM traders WHERE phone_number = '2348011111111';"

# 2. Delete the Redis onboarding state
docker compose exec redis redis-cli DEL "onboarding:state:2348011111111"
```

Now the phone number is completely fresh. Sending any message will restart the welcome flow.

---

## 14. What to check in the logs

Run logs with:

```bash
docker compose logs -f app
```

For a healthy onboarding you should see these log lines in order:

```
INFO  Published event=message.received tenant=tenant-test-001 ...
INFO  Message persisted event_id=... conversation_id=... message_id=...
INFO  Published event=conversation.message_saved ...
INFO  Registering onboarding handler (all tenants)          ← startup only
INFO  Notification sent id=... recipient=234801... event_id=onboarding_reply...
```

On completion:
```
INFO  Onboarding complete phone=2348011111111 slug=mama-caro-provisions category=provisions
INFO  Notification sent ... event_id=onboarding_reply..._complete
```

For Path A (photo):
```
INFO  OCR extracted 342 chars
INFO  Claude extracted 14 products from 342 chars of text
INFO  Notification sent ... event_id=onboarding_reply..._ack
INFO  Notification sent ... (the product list message)
```

For Path B (voice):
```
INFO  Whisper transcribed 187 chars from audio/ogg audio
INFO  Claude extracted 6 products from 187 chars of text
```

**Red flags in logs:**

| Log message | What it means | Fix |
|-------------|---------------|-----|
| `Onboarding reply failed phone=... NotFoundError` | WhatsApp channel not registered | Run the `/channels/whatsapp/connect` POST (section 2b) |
| `GOOGLE_VISION_API_KEY not set — OCR unavailable` | Missing key | Add to `.env` |
| `OPENAI_API_KEY not set — transcription unavailable` | Missing key | Add to `.env` |
| `ANTHROPIC_API_KEY not set — product extraction unavailable` | Missing key | Add to `.env` |
| `OCR returned empty text` | Photo unreadable | Expected fallback behaviour |
| `Whisper returned empty transcript` | Audio inaudible | Expected fallback behaviour |
| `Product extraction JSON parse failed` | Claude returned unexpected format | Check Anthropic API status |

---

## 15. Common failures and fixes

### App starts but onboarding handler never fires

**Cause:** Redis pub/sub is not connected.

**Check:**
```bash
docker compose exec redis redis-cli PING
# Should return: PONG
```

Check logs for: `Subscribed to channel: chattosales.events.*...`

---

### State machine gets stuck on a step

**Cause:** A previous test left stale Redis state.

**Fix:** Reset the trader (section 13).

---

### "conversation.message_saved" never published

**Cause:** Conversation service failed to persist the message (e.g. DB not reachable).

**Check:**
```bash
docker compose exec postgres psql -U postgres -d chattosales -c "SELECT COUNT(*) FROM messages;"
```

If this fails, PostgreSQL is not healthy. Check: `docker compose ps postgres`.

---

### Replies send but are not received on the actual phone

**Cause:** WhatsApp access token expired or wrong `WHATSAPP_PHONE_NUMBER_ID`.

**Check logs for:**
```
WhatsApp API error status=401
```

**Fix:** Refresh the access token in Meta Developer Console and re-run the
`/channels/whatsapp/connect` endpoint.

---

### "Onboarding reply failed ... already sent for event_id"

This is not an error — it means the same message was processed twice (duplicate event).
The idempotency guard in `NotificationService` is working correctly.
