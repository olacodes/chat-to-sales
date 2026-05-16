# Feature 10: Growth & Marketing Tools — Task Tracker

## Overview

Features designed to help traders sell more. Every feature answers the trader's question: "Will this make me more money?" Core philosophy: automate what traders already do manually (broadcast, follow-up, restock alerts) and add intelligence they can't do alone (cross-sell, loyalty, profit tracking).

## Build Priority

| # | Feature | Impact | Effort | Status |
|---|---------|--------|--------|--------|
| 1 | Broadcast to past customers | Massive | Medium | ⬜ |
| 2 | Smart follow-up (abandoned interest) | High | Medium | ⬜ |
| 3 | Repeat order shortcut | High | Small | ⬜ |
| 4 | Customer purchase history | High | Small | ⬜ |
| 5 | Flash sale announcements | High | Medium | ⬜ |
| 6 | New stock alerts | Medium | Medium | ⬜ |
| 7 | Cross-sell suggestions | Medium | Medium | ⬜ |
| 8 | Expense & profit tracker | Medium | Small | ⬜ |
| 9 | Scheduled broadcast | Medium | Small | ⬜ |
| 10 | Loyalty points / VIP | Medium | Medium | ⬜ |
| 11 | Back in stock notifications | Medium | Medium | ⬜ |
| 12 | Voice broadcast | Medium | Medium | ⬜ |

---

## Feature Details

### 1. Broadcast to Past Customers

**What:** Trader sends one message to ALL past customers at once.

**Why:** This is the #1 thing Nigerian traders do manually — scroll through contacts, forward messages one by one. Automating this is instant value.

**How it works:**
- Every customer who orders gets added to the trader's "customer list" automatically
- Trader types BROADCAST or taps it in the menu
- Types the message (or picks a product from catalogue)
- System sends to all past customers via WhatsApp
- Shows delivery report: "Sent to 47 customers"

**WhatsApp constraint:** Meta limits business-initiated messages. Need approved message templates or use the 24-hour conversation window. May need to use WhatsApp broadcast list API or send individual messages within conversation windows.

**Implementation:**
- Backend: `customer_list` table (auto-populated from orders + conversations)
- Backend: `POST /broadcast` endpoint — queues messages
- Backend: Rate-limited sender (avoid WhatsApp spam limits)
- WhatsApp: Send via conversation window if within 24h, otherwise use template message
- Menu: BROADCAST command or Marketing → Broadcast

---

### 2. Smart Follow-up (Abandoned Interest)

**What:** Customer inquires about a product but doesn't order → 24h later, auto-reminder.

**Why:** Traders lose 60%+ of inquiries because they forget to follow up. One reminder = recovered sale.

**How it works:**
- Customer asks "how much is iPhone 12?" → conversation tracked
- No order created within 24 hours
- Auto-send: "Hi Bimpe! Still interested in the UK iPhone 12 128GB (N330,000)? It's selling fast. Reply YES to order."
- If customer replies YES → order flow starts
- If ignored → no more follow-ups (not pushy)

**Implementation:**
- Track conversations where a product was discussed but no order created
- Scheduler job: check for stale inquiries > 24h
- Send one follow-up per inquiry (not repeated)
- Business hours gated (8am-8pm WAT)

---

### 3. Repeat Order Shortcut

**What:** One-tap reorder for regular customers.

**Why:** Provisions/food traders have repeat customers who buy the same thing weekly/monthly.

**How it works:**
- Customer who bought Garri last month gets a suggestion:
  "Hi Mama Tayo! Ready to reorder? Your last purchase: Garri 50kg - N2,500. Reply YES to confirm."
- Or customer types REORDER → shows last order → one tap to confirm
- Scheduler: for customers with 2+ orders of the same product, send reorder prompt after the average interval

**Implementation:**
- Detect repeat purchase patterns (same product, same customer, >1 order)
- Calculate average reorder interval
- Schedule reorder prompt at the right time
- REORDER command for customer-initiated reorder

---

### 4. Customer Purchase History

**What:** Trader can look up any customer's full order history.

**Why:** Personalized service = loyalty. "Ah Bro Sodiq, you like the Pro models right?"

**How it works:**
- Trader types: WHO IS 08166041471 or WHO IS Sodiq
- Response: "Sodiq Olatunde — 3 orders, N1.2M total. Last order: UK 11 128GB (May 5). Regular customer."
- Dashboard: Customer page with full history, order frequency, total spend
- Trader can see: top customers, most loyal, highest spenders

**Implementation:**
- Already have order data with customer_phone + customer_name
- New WhatsApp command: WHO IS <name or phone>
- Aggregate: total orders, total spend, last order, favorite products
- Dashboard: /customers page with search + history

---

### 5. Flash Sale Announcements

**What:** Time-limited discounts broadcast to all customers.

**Why:** Nigerian market psychology is urgency-driven. Scarcity sells.

**How it works:**
- Trader sets: "20% off all Ankara — today only!" or "iPhone 12 64GB N250k → N220k until 6pm"
- System broadcasts to all past customers
- Store page shows the sale badge
- Status card auto-generates with "SALE" / "LIMITED OFFER" badge
- Sale auto-expires at the set time

**Implementation:**
- `flash_sales` table: product, discount, start_time, end_time
- Broadcast to customer list on start
- Store page: sale badge overlay on discounted products
- Auto-expire: scheduler removes discount at end_time
- Status Kit: generates sale-themed cards

---

### 6. New Stock Alerts

**What:** Auto-notify customers when new products are added.

**Why:** Traders constantly get "do you have...?" questions. When stock arrives, they forget who asked.

**How it works:**
- Trader adds new product to catalogue
- System checks: which customers previously asked about similar products?
- Auto-sends: "New stock at Ola Phones! UK 14 Pro Max just landed - N800k"
- Also sends to customers who opted in to "new stock alerts"

**Implementation:**
- Track product inquiries that didn't result in orders (product not in catalogue)
- On catalogue add: match new product name against past inquiries (fuzzy)
- Send notification to matched customers
- Optional: customer subscribes to category alerts

---

### 7. Cross-sell Suggestions

**What:** "Customers who bought X also bought Y"

**Why:** Increases average order value by 15-30%.

**How it works:**
- After order confirmation: "Customers who bought iPhone 12 also added: Screen Protector (N2,000), Phone Case (N3,500). Would you like to add any?"
- Based on actual co-purchase data from the trader's order history
- Interactive: customer taps to add to order

**Implementation:**
- Analyze order items: products frequently bought together
- After order confirmation, suggest top 2-3 co-purchased items
- Interactive buttons: [Add Screen Protector N2,000] [No thanks]
- Only suggest if confidence is high (>3 co-purchases)

---

### 8. Expense & Profit Tracker

**What:** Simple cost tracking → automatic profit calculation.

**Why:** Most Nigerian traders don't know their actual profit margin.

**How it works:**
- Trader types: COST Indomie Carton 7500 (what they paid the supplier)
- System tracks: selling price N8,500 - cost N7,500 = N1,000 profit (13%)
- Weekly report adds: "Revenue: N485,000 | Costs: N380,000 | Profit: N105,000 (22%)"
- Dashboard: profit margin chart per product

**Implementation:**
- `product_costs` table: product_name, cost_price, updated_at
- COST command in WhatsApp
- Weekly report: add profit section (revenue - sum of costs)
- Dashboard: margin visualization

---

### 9. Scheduled Broadcast

**What:** Write now, send later.

**Why:** Timing matters. 8am post = maximum visibility. Traders are busy and forget.

**How it works:**
- Trader types: SCHEDULE "Fresh tomatoes arrived!" tomorrow 8am
- Or from dashboard: compose message, pick date/time, select audience
- System sends at the scheduled time
- Confirmation: "Message scheduled for tomorrow 8:00 AM. Will be sent to 47 customers."

**Implementation:**
- Extend existing `scheduled_messages` table
- Support broadcast-type scheduled messages
- APScheduler picks up and sends at the right time
- Dashboard: scheduled message management UI

---

### 10. Loyalty Points / VIP

**What:** Points-based reward system for repeat customers.

**Why:** Systematic retention. Traders already give informal discounts to regulars.

**How it works:**
- Every N10,000 spent = 1 point (configurable)
- 10 points = N5,000 discount
- Customer gets notified after each order: "You earned 2 points! Total: 8 points. 2 more for N5,000 off!"
- Trader sees top loyal customers in dashboard

**Implementation:**
- `loyalty_points` table: customer_phone, trader_phone, points, total_earned
- Auto-award after paid orders
- Redemption: customer mentions "use my points" or trader applies manually
- Weekly report: add loyalty section

---

### 11. Back in Stock Notifications

**What:** Notify customers when a previously unavailable product returns.

**Why:** Never lose a sale to stockouts.

**How it works:**
- Customer: "Do you have iPhone 14?" → Trader: "Out of stock"
- System tags: customer wants iPhone 14
- When trader adds iPhone 14 to catalogue: auto-notify
- "Great news! iPhone 14 is back in stock at Ola Phones - N500k. Order now?"

**Implementation:**
- Track "product not found" / "out of stock" conversations
- Store: customer_phone + product_keywords
- On catalogue add: fuzzy match against waitlist
- Send notification to matched customers

---

### 12. Voice Broadcast

**What:** Trader records one voice note → sends to all customers.

**Why:** Very Nigerian. Personal, warm, builds trust. Traders love voice notes.

**How it works:**
- Trader sends a voice note to ChatToSales with caption: BROADCAST
- System forwards the voice note to all past customers
- Delivery report: "Voice broadcast sent to 47 customers"

**Implementation:**
- Detect voice note + BROADCAST keyword
- Download audio from WhatsApp
- Upload to R2
- Send via WhatsApp audio URL to all customers in list
- Rate-limited to avoid spam

---

## Architecture Notes

### Customer List (shared across features)

All broadcast/notification features depend on a **customer list** per trader:
- Auto-populated from orders (customer_phone, customer_name)
- Auto-populated from conversations
- Deduplicated by phone number
- Stores: first_order_date, last_order_date, total_orders, total_spend
- GDPR/privacy: customers can opt out (reply STOP)

### Rate Limiting (WhatsApp)

Meta limits business-initiated messages:
- Within 24h conversation window: unlimited messages
- Outside window: need approved template messages
- Rate limit: ~80 messages/second (business tier dependent)
- Strategy: queue messages, send at controlled rate, retry on failure

### Menu Integration

New Marketing sub-menu items:
- Broadcast Message
- Scheduled Messages
- Flash Sale
- Customer List
- Loyalty Dashboard

---

## Key Files (to be created)

| File | Purpose |
|------|---------|
| `app/modules/marketing/broadcast.py` | Broadcast message service + rate limiter |
| `app/modules/marketing/followup.py` | Smart follow-up scheduler |
| `app/modules/marketing/loyalty.py` | Points system |
| `app/modules/marketing/models.py` | CustomerList, FlashSale, LoyaltyPoints models |
| `app/modules/marketing/router.py` | Dashboard API endpoints |
| `alembic/versions/030_*.py` | Migrations for marketing tables |
