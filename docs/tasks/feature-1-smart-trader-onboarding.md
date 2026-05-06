# Feature 1: Smart Trader Onboarding — Task Tracker

## Done

| # | Task | Description |
|---|------|-------------|
| ✅ | WhatsApp webhook ingestion | `POST /webhooks/whatsapp` with HMAC-SHA256 signature verification, handles text/image/audio/interactive message types |
| ✅ | Onboarding state machine | 8-step Redis-backed FSM: AWAITING_NAME → AWAITING_CATEGORY → AWAITING_CATALOGUE → path-specific → completion |
| ✅ | Welcome message & name capture | Nigerian English welcome, 2-60 char validation, trimming |
| ✅ | Category selection | 7 numbered categories (provisions, fabric, food, electronics, cosmetics, building, other) with free-text for "other" |
| ✅ | Path A: Photo OCR | Download WhatsApp image → Google Vision OCR → Claude Haiku product extraction → confirmation with corrections |
| ✅ | Path B: Voice transcription | Download WhatsApp audio → OpenAI Whisper (Nigerian English prompt) → Claude Haiku product extraction → confirmation |
| ✅ | Path C: Q&A one-by-one | 30 pre-loaded items per category, sequential price entry, skip support, checkpoint every 5 items |
| ✅ | Path D: Skip (recommended) | Immediate completion with empty catalogue, learns passively from orders |
| ✅ | Catalogue templates | 30 starter items per category (provisions, fabric, food, electronics, cosmetics, building), empty for "other" |
| ✅ | Media confirmation with corrections | "yes but number 2 na Rice 50kg = 63000" parsed via regex for item number, name, and price |
| ✅ | Store slug generation | Sanitize business name → lowercase → hyphens → deduplicate (append -2, -3) |
| ✅ | Trader record creation | Persists to PostgreSQL: phone, name, category, slug, tier, catalogue JSON |
| ✅ | Completion messages | Store link + command guide + shareable customer message |
| ✅ | Trader identity caching | Redis cache (1h TTL) at `trader:phone:{phone}` for fast order handler lookups |
| ✅ | Welcome-back detection | If session inactive >6h, sends "Welcome back!" and resumes from exact step |
| ✅ | Pending prompt recovery | Failed outbound messages stored in state, resent on next inbound |
| ✅ | Onboarding trigger guard | Only `hi, hello, hey, start, register, join` trigger onboarding for unknown senders |
| ✅ | Order handler yield | Order handler checks onboarding state and yields if active — prevents duplicate processing |
| ✅ | Session TTL | 7-day Redis TTL prevents indefinite state accumulation |
| ✅ | Price parsing | Supports: digits (8500), comma (8,500), k-notation (8.5k), Yoruba numbers |
| ✅ | Image resize | 768x768 max with Pillow before Claude Vision calls (50% token savings) |
| ✅ | Phone number normalization | Nigerian local (08012345678) → E.164 (2348012345678) in auth schemas |
| ✅ | First dashboard login | OTP → create User + Tenant → migrate orders from platform tenant → bust Redis caches |
| ✅ | Superadmin auto-seed | ADMIN_PHONE/EMAIL/PASSWORD env vars → auto-create admin on startup |

## Undone

| # | Task | Description | MVP |
|---|------|-------------|-----|
| ✅ | Catalogue editing via WhatsApp | Let traders add/remove/update products after onboarding through chat commands (e.g., "ADD Milo 3500", "REMOVE Garri", "PRICE Indomie 9000") | ✅ Yes |
| ✅ | Onboarding re-entry | Allow completed traders to re-run onboarding to rebuild their catalogue from scratch | ✅ Yes |
| ✅ | Category change command | `CATEGORY` command to let trader switch business category after onboarding | ✅ Yes |
| ✅ | Photo gallery during onboarding | Let traders send multiple photos (e.g., 3 pages of a price list) and combine the OCR results | ✅ Yes |
| ✅ | Onboarding analytics | Track completion rates per path, drop-off points, average time to complete in the admin dashboard | ✅ Yes |
| ✅ | Web-based onboarding | Allow traders to sign up and set up their store via the website instead of WhatsApp only | ⬜ No |
| ⬜ | Onboarding video tutorial | Auto-send a short WhatsApp video guide after the store link is created | ⬜ No |
| ⬜ | Tier upgrade prompt | After 30 days on Ofe tier, suggest upgrading to Oja with feature comparison | ⬜ No |
| ⬜ | Bulk product import | CSV/Excel upload via dashboard for traders with large catalogues (100+ items) | ⬜ No |
| ⬜ | Multi-language support | Onboarding copy in Yoruba, Igbo, or Hausa — auto-detect from phone locale or let trader choose | ⬜ No |
| ⬜ | Onboarding flow testing tool | Admin tool to simulate the onboarding conversation without a real WhatsApp number (for QA) | ⬜ No |

## Nice to Have

| # | Task | Description | MVP |
|---|------|-------------|-----|
| 💡 | WhatsApp template messages | Use pre-approved Meta templates for welcome/completion messages — higher delivery reliability, avoids 24h window issues | ⬜ No |
| 💡 | Onboarding progress bar | Show "Step 2 of 4" in messages so trader knows how far they are | ⬜ No |
| 💡 | Smart category detection | Auto-detect business category from the first few products instead of asking | ⬜ No |
| 💡 | Referral onboarding | "Mama Caro referred you" — pre-fill category from referrer's store, track referral chains | ⬜ No |
| 💡 | Voice-first onboarding | Let the entire onboarding happen via voice notes (not just catalogue path B) — speak name, speak category | ⬜ No |
| 💡 | Handwriting OCR improvement | Fine-tune Claude prompt for common Nigerian handwriting styles and market shorthand | ⬜ No |
| 💡 | Business verification | Optional NIN/CAC number entry for "verified trader" badge on store page | ⬜ No |
| 💡 | Onboarding A/B testing | Test different welcome messages, category orders, or default paths to optimize completion rate | ⬜ No |
