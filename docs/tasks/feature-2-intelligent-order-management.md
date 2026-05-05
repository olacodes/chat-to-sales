# Feature 2: Intelligent Order Management — Task Tracker

## Done

| # | Task | Description |
|---|------|-------------|
| ✅ | Order state machine | 5 states (INQUIRY → CONFIRMED → PAID → COMPLETED / FAILED) with validated transitions |
| ✅ | NLP Layer 1 (regex) | Trader commands, YES/NO detection, order trigger words, item extraction with quantities — <5ms |
| ✅ | NLP Layer 2 (Claude Haiku) | Fallback for ambiguous messages (confidence <0.5), handles Pidgin/Yoruba, returns structured JSON |
| ✅ | Yoruba number support | meji=2, meta=3, merin=4, marun=5, mefa=6, meje=7, mejo=8, mesan=9, mewa=10, ogun=20, ogoji=40 |
| ✅ | English word numbers | one through ten in both NLP and quantity selection |
| ✅ | Customer direct message orders | Free-text parsing → catalogue price lookup → order summary → YES/NO confirmation |
| ✅ | Store cart orders (ORDER:{slug}) | Pre-structured messages from store page, parsed via regex, items matched to catalogue |
| ✅ | Voice note orders | Download audio → Whisper transcription → same NLP pipeline as text |
| ✅ | Image inquiry orders | pHash matching → Claude Vision → quantity picker → trader notification (see Feature 3) |
| ✅ | Trader commands | CONFIRM, CANCEL, PAID, DELIVERED + order ref lookup via UUID prefix (8 hex chars) |
| ✅ | Interactive buttons (trader) | Confirm/Decline buttons on order notifications, button ID = full command |
| ✅ | Interactive buttons (customer) | YES/NO buttons on order summaries |
| ✅ | Quantity list picker | WhatsApp list message with Buy 1-5 + Cancel, shows price × quantity per row |
| ✅ | Typed quantity support | Digits ("7"), English words ("seven"), Yoruba words ("meji"), phrases ("I want 7") |
| ✅ | Customer routing sessions | Redis key `customer:routing:{phone}` (4h TTL) links follow-up messages to correct trader |
| ✅ | Order sessions | Redis key `order:session:{tenant_id}:{phone}` (24h TTL) for AWAITING_CONFIRMATION / AWAITING_CLARIFICATION |
| ✅ | Trader identity caching | Redis: by phone (1h), by tenant (1h), by slug (1h) with `{}` sentinel for "not found" |
| ✅ | Clarification flow | Claude detects ambiguity → asks ONE specific question → re-parses with context |
| ✅ | Missing price handling | Items not in catalogue → prompt customer to provide prices manually |
| ✅ | Order notifications | Customer: summary, pending, confirmed, cancelled. Trader: order received, confirmed, cancelled, paid, delivered |
| ✅ | Notification idempotency | `event_id` as dedup key — same event never produces two WhatsApp sends |
| ✅ | Notification error swallowing | Failed sends logged at ERROR but never crash the handler loop |
| ✅ | Photo with order notification | Trader receives customer's product photo + interactive buttons as reply-to (linked visually) |
| ✅ | Reply-to message chaining | `_reply_image` returns wamid, `_reply_interactive` accepts `context_message_id` for quoted replies |
| ✅ | WhatsApp list message support | `send_list()` + `_dispatch_whatsapp_list()` in NotificationService |
| ✅ | Order REST API | GET/POST /orders, GET /orders/{id}, POST confirm/pay/complete/fail, POST items |
| ✅ | Superadmin order view | `is_superadmin` in JWT → tenant filter omitted → sees all orders cross-tenant |
| ✅ | trader_phone on Order | Stored for tenant migration and admin visibility |
| ✅ | Tenant migration at login | Orders + conversations + messages migrated from platform tenant to trader's dedicated tenant |
| ✅ | Redis cache busting | After tenant migration, stale `trader:phone`, `trader:tenant`, `trader:slug` keys deleted |
| ✅ | Credit sale status handler | Listens for `credit_sale.status_changed` → auto-completes linked order when settled/written_off |

## Undone

| # | Task | Description | MVP |
|---|------|-------------|-----|
| ⬜ | Order timeout | Auto-cancel INQUIRY orders after X hours if trader doesn't confirm — prevents stale orders piling up | ✅ Yes |
| ⬜ | Dashboard order management | Trader can confirm/cancel orders from the web dashboard — not everyone has WhatsApp open all day | ✅ Yes |
| ⬜ | Order history for customers | Customer types "my orders" or "status" → sees list of recent orders with current state | ✅ Yes |
| ⬜ | Receipt generation | Auto-generate and send a receipt (image or formatted text) after order completion or payment | ✅ Yes |
| ⬜ | Automated trader follow-up | If trader hasn't confirmed in 2h, auto-send a reminder — reduces order abandonment | ✅ Yes |
| ⬜ | Payment integration (Paystack) | Auto-generate Paystack payment link for confirmed orders, customer pays inline (Feature 6) | ✅ Yes |
| ⬜ | Order editing | Allow customer or trader to modify items/quantities after order creation (currently must cancel and re-order) | ⬜ No |
| ⬜ | Group order collection | ChatToSales joins a WhatsApp group, collects orders from members, sends consolidated sheet to trader | ⬜ No |
| ⬜ | Delivery tracking | Status updates (dispatched, en-route, delivered) with real-time customer notifications | ⬜ No |
| ⬜ | Bulk order operations | Trader can confirm/cancel multiple orders at once from dashboard or WhatsApp | ⬜ No |
| ⬜ | Order search via WhatsApp | Trader types "ORDERS TODAY" or "ORDERS +2348012345678" to query orders without the dashboard | ⬜ No |
| ⬜ | Conversation handoff | When NLP can't understand after 2 attempts, hand off the conversation directly to the trader instead of repeating prompts | ⬜ No |
| ⬜ | Order notes | Trader or customer can add notes to an order (e.g., "deliver to back gate", "extra pepper") | ⬜ No |

## Nice to Have

| # | Task | Description | MVP |
|---|------|-------------|-----|
| 💡 | Smart reorder | "Order same as last time" — repeat a previous order with one tap | ⬜ No |
| 💡 | Order scheduling | "Deliver on Friday" — schedule orders for future delivery with reminder | ⬜ No |
| 💡 | Price negotiation detection | Detect when customer is haggling ("can you do 7000?") and escalate to trader (Feature 5) | ⬜ No |
| 💡 | Multi-item image orders | Customer sends photo of a handwritten shopping list → OCR → parse multiple items at once | ⬜ No |
| 💡 | Order priority | Urgent orders flagged ("I need this ASAP") and shown first in trader's notification queue | ⬜ No |
| 💡 | Customer loyalty tracking | Track repeat customers, show "returning customer (5th order)" badge to trader | ⬜ No |
| 💡 | Order templates | Trader creates reusable bundles ("school provisions pack = Indomie + Rice + Milk") customers order by name | ⬜ No |
| 💡 | Multi-currency | Support USD, GBP for diaspora customers ordering from Nigerian traders | ⬜ No |
| 💡 | Order analytics for trader | WhatsApp summary: "This week: 23 orders, N145,000 revenue, top product: Indomie" | ⬜ No |
| 💡 | Customer satisfaction survey | After order completion, ask customer to rate 1-5 — aggregate for trader insights | ⬜ No |
| 💡 | Partial order fulfillment | Trader can confirm some items but mark others as out-of-stock, adjusting the total | ⬜ No |
| 💡 | Order forwarding | Trader can forward an order to another trader if they don't have the product | ⬜ No |
