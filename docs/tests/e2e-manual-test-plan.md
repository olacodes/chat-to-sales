# ChatToSales — End-to-End Manual Test Plan

## How to Use This Document

- Test each journey in order (they build on each other)
- Mark **Status** as: PASS / FAIL / BLOCKED / SKIPPED
- Write bug details in **Notes** — include the exact message sent and the response received
- Test on a real phone with WhatsApp (not web simulator)
- Test the dashboard on both desktop and mobile browser
- Test in both light mode and dark mode

## Prerequisites

- [ ] Backend running (`uvicorn app.main:app`)
- [ ] Frontend running (`npm run dev`)
- [ ] Redis running
- [ ] PostgreSQL running with migrations applied
- [ ] WhatsApp webhook connected (ngrok or production URL)
- [ ] `.env` has: OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_VISION_API_KEY, PAYSTACK_SECRET_KEY
- [ ] A test phone number that is NOT the platform WhatsApp number
- [ ] A second phone number to act as a customer

---

## Journey 1: Trader Onboarding

**Persona:** New trader, first time using ChatToSales

### 1.1 First Message

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 1 | Send "Hi" to the platform WhatsApp number | Welcome message in proper English, asks for business name | | |
| 2 | Send "Hello" from the same number | Should NOT create a duplicate session — continues from step 1 | | |
| 3 | Send a single character "A" | Rejected — name must be 2-60 characters | | |
| 4 | Send "Mama Caro Provisions" | Accepted, asks to pick a business category (numbered list 1-7) | | |
| 5 | Send "1" (Provisions) | Category confirmed, shows 4 catalogue path options | | |

### 1.2 Path D — Skip (Recommended)

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 6 | Choose Path D (skip) | Onboarding complete, store link sent, command guide shown | | |
| 7 | Visit the store link in a browser | Store page loads with business name, category, empty catalogue message | | |
| 8 | Send another message to WhatsApp | Should NOT trigger onboarding again — routed to order handler | | |

### 1.3 Path A — Photo OCR

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 9 | Start fresh onboarding (new number or reset) | Complete name + category steps | | |
| 10 | Choose Path A, send a clear price list photo | "Reading your price list..." then extracted products shown for confirmation | | |
| 11 | Send a blurry/dark photo | Should ask for a clearer photo or offer alternative path | | |
| 12 | Confirm the extracted products | Catalogue saved, onboarding complete | | |

### 1.4 Path B — Voice Note

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 13 | Start fresh onboarding, choose Path B | Prompts to send a voice note | | |
| 14 | Send a clear voice note listing products and prices | Transcribed, products extracted, shown for confirmation | | |
| 15 | Send a very noisy/unclear voice note | Should ask to resend or type instead | | |

### 1.5 Session Recovery

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 16 | Start onboarding, complete name step, wait 10+ minutes | Session persists in Redis | | |
| 17 | Send a message after the gap | "Welcome back!" — resumes from where you left off | | |

---

## Journey 2: Store Page (Browser)

**Persona:** Customer browsing a trader's store

### 2.1 Basic Store Page

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 18 | Visit `chattosales.com/stores/{slug}` | Store loads: name, category, catalogue with prices | | |
| 19 | Visit a non-existent slug | 404 page shown (animated shopping bag) | | |
| 20 | Check page source for JSON-LD | `<script type="application/ld+json">` with LocalBusiness + Product schemas | | |
| 21 | Share store link on WhatsApp | Rich preview: store name, product count, green OG image | | |

### 2.2 Product Search

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 22 | Visit a store with 10+ products | Search bar visible above catalogue | | |
| 23 | Type a product name in search | List filters instantly, matching products shown | | |
| 24 | Type a non-existent product | "No products match" message shown | | |
| 25 | Clear search | Full catalogue restored | | |
| 26 | Visit a store with < 10 products | Search bar NOT shown (unnecessary) | | |

### 2.3 Cart & Ordering

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 27 | Tap + on a product | Quantity shows 1, sticky order bar appears at bottom | | |
| 28 | Tap + again | Quantity increments, total updates | | |
| 29 | Tap - to remove | Quantity decrements, bar disappears at 0 | | |
| 30 | Add 2-3 items, tap "Order on WhatsApp" | Opens WhatsApp with pre-filled ORDER:{slug} message and items | | |

### 2.4 Bank Details

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 31 | Visit store where trader has bank details set | "Payment Details" card visible: bank, account, name | | |
| 32 | Visit store where trader has NO bank details | No payment section shown | | |

### 2.5 Performance

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 33 | Load store page on throttled 3G (Chrome DevTools > Network > Slow 3G) | Loading skeleton appears instantly, content loads within 3s | | |
| 34 | Check that no framer-motion JS loads on store page | Network tab: no framer-motion chunk in JS bundles | | |
| 35 | Reload same store page | Should be near-instant (CDN cache hit) | | |

---

## Journey 3: Customer Order Flow (WhatsApp)

**Persona:** Customer ordering from a trader's store

### 3.1 Cart Order (from Store Page)

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 36 | Send the pre-filled ORDER:{slug} message from the store page | Order summary shown with items, prices, total. YES/NO buttons | | |
| 37 | Tap YES | "Your order has been sent to {trader}!" — trader gets notification with Confirm/Decline buttons | | |
| 38 | (As trader) Tap Confirm | Trader sees Paid/Credit buttons. Customer gets confirmation + bank details (if set) | | |

### 3.2 Freeform Text Order

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 39 | Send "I want 2 bags of rice and 1 carton of Indomie" | Smart parser finds products, shows summary with prices from catalogue | | |
| 40 | Send "I want to buy an iPhone" (not in catalogue) | Clarification: "I don't have that in the catalogue" or asks what they want | | |
| 41 | Send "give me three milo" (Yoruba number + informal) | Parsed correctly: 3x Milo with price | | |

### 3.3 Voice Note Order

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 42 | Send a voice note saying "I want 2 bags of rice" | Transcribed, parsed, summary shown | | |
| 43 | Send a very short/inaudible voice note | "I couldn't understand that voice note" message | | |

### 3.4 Image Inquiry

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 44 | Send a photo of a product that exists in catalogue | Matched via pHash or Claude Vision, price shown, quantity picker | | |
| 45 | Send a photo of an unknown product | "Let me ask the trader" — forwarded to trader | | |
| 46 | (As trader) Reply with "Milo 3500" to the image inquiry | Product saved, customer notified with price | | |
| 47 | Send the same product photo again | Should match via pHash (no Claude call), instant response | | |

### 3.5 Smart Filtering (Message Noise)

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 48 | After placing an order, send just a thumbs up emoji | No response (emoji filter) | | |
| 49 | Send "thanks" after order confirmation | No response (quiet mode — 30 min post-order) | | |
| 50 | Send "ok" or "alright" | No response (IGNORE intent) | | |
| 51 | Send "how are you" or "where is your shop" | Friendly chitchat reply, no order created | | |
| 52 | Send "I want rice" during quiet mode | Should still respond (ORDER intent breaks through quiet mode) | | |

---

## Journey 4: Trader Order Management (WhatsApp)

**Persona:** Trader managing incoming orders

### 4.1 Menu & Commands

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 53 | Send "MENU" | Interactive list with 9 options across 3 sections (Orders, Catalogue, Store) | | |
| 54 | Tap "Active Orders" in menu | List of active orders (or "no active orders" message) | | |
| 55 | Tap an order in the list | Context-appropriate buttons shown (Confirm/Cancel for inquiry, Paid/Credit for confirmed) | | |

### 4.2 Order Lifecycle

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 56 | Type "CONFIRM {ref}" for an inquiry order | Order CONFIRMED, customer notified with bank details | | |
| 57 | Type "PAID {ref}" for a confirmed order | Order PAID | | |
| 58 | Type "DELIVERED {ref}" for a paid order | Order COMPLETED | | |
| 59 | Type "CANCEL {ref}" for an inquiry order | Order CANCELLED, customer notified | | |
| 60 | Type "CONFIRM badref123" | "Could not find an order with ref badref123" | | |
| 61 | Type "PAID {ref}" for an inquiry order (wrong state) | Error: "Cannot mark order as paid" (must be confirmed first) | | |

### 4.3 Credit Flow

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 62 | After confirming an order, tap "Credit" instead of "Paid" | Order marked as credit, credit sale created, "Type WHO OWES ME" prompt | | |
| 63 | Type "WHO OWES ME" | Debt list picker showing the credit customer | | |

### 4.4 Order Reminders (Automated)

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 64 | Leave an inquiry order unconfirmed for 1+ hour | Trader receives reminder with Confirm/Decline buttons | | |
| 65 | Verify reminder only comes during business hours (8am-8pm WAT) | No reminders at midnight | | |

---

## Journey 5: Payment Flow

**Persona:** Customer paying for a confirmed order

### 5.1 Payment Receipt Detection — Text

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 66 | (As customer) After receiving bank details, type "paid" | "I've notified {trader} about your payment" | | |
| 67 | Type "I've paid" | Same — payment detected | | |
| 68 | Type "sent" | Same — payment detected | | |
| 69 | Type "transferred" | Same — payment detected | | |
| 70 | Type "check your account" | Same — payment detected | | |
| 71 | Type "e don pay" (Pidgin) | Same — payment detected | | |

### 5.2 Payment Receipt Detection — Screenshot

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 72 | Send a photo (any image) while having a confirmed order | Treated as payment screenshot, trader notified with "They also sent a payment screenshot" | | |

### 5.3 Trader Confirmation

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 73 | (As trader) Tap "Payment Received" | Order marked PAID, customer gets "payment confirmed!" | | |
| 74 | (As trader) Tap "Not Received" | Customer notified to double-check | | |

### 5.4 Edge Cases

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 75 | Customer types "paid" with NO confirmed order | "I don't see a confirmed order to match your payment" | | |
| 76 | Customer types "paid" during quiet mode (within 30min of order) | Should break through quiet mode and detect payment | | |
| 77 | Customer sends image with NO confirmed order (no routing session) | Treated as product inquiry, NOT payment screenshot | | |

---

## Journey 6: Negotiation

**Persona:** Customer haggling on price

### 6.1 Specific Price Offer

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 78 | Send "can you do 5000?" while browsing | "I've asked the trader about the price" — customer NOT blocked | | |
| 79 | (As trader) See notification with Accept/Counter/Decline buttons | Shows product, your price, their offer | | |
| 80 | Tap "Accept" | Customer notified: "Great news! Accepted at N5,000. Reply YES to confirm" | | |

### 6.2 Counter-Offer

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 81 | (Different negotiation) Trader taps "Counter-offer" | "Type your counter-offer price" prompt | | |
| 82 | Trader types "7500" | Customer notified: "{trader} can do N7,500. YES/NO?" | | |

### 6.3 Decline

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 83 | (Different negotiation) Trader taps "Decline" | Customer notified: "Can't go below {price}. Order at {price}? YES/NO" | | |

### 6.4 Non-Blocking

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 84 | While negotiation is pending, customer sends a new order | New order processed normally — negotiation doesn't block | | |
| 85 | General haggling: "too expensive" (no specific price) | Trader notified, customer gets "I've asked the trader" | | |

---

## Journey 7: Debt Tracker

**Persona:** Trader tracking who owes them

### 7.1 Manual Debt Creation

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 86 | Type "DEBT Iya Bimpe 5000" | "Recorded: Iya Bimpe owes you N5,000" | | |
| 87 | Type "DEBT Mama Tayo 3000" | Second debt recorded | | |
| 88 | Type "WHO OWES ME" | Interactive list: 2 debtors with amounts, total outstanding | | |

### 7.2 Debt Settlement

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 89 | Tap a debtor name in the list | Buttons: Settled / Remind | | |
| 90 | Tap "Settled" | Debt cleared, confirmation shown | | |
| 91 | Type "PAID Mama Tayo 1500" (partial payment) | "Received N1,500. Remaining: N1,500" | | |
| 92 | Type "PAID Mama Tayo 1500" again | Debt fully settled | | |

### 7.3 Debt Reminders

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 93 | Tap "Remind" on a debtor | "Reminder sent to {name}" — customer gets gentle reminder | | |
| 94 | Create a debt with no linked conversation | Tap "Remind" — should show "no linked conversation" error | | |

### 7.4 Credit Order to Debt

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 95 | Confirm an order, tap Credit | Credit sale created with order link | | |
| 96 | Type "WHO OWES ME" | Credit order customer appears in debt list | | |
| 97 | Settle the credit debt | Linked order should complete (credit_sale.status_changed event) | | |

---

## Journey 8: Catalogue Management (WhatsApp)

**Persona:** Trader updating their product catalogue

### 8.1 Add Products

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 98 | Type "ADD Milo 3500" | "Added Milo at N3,500" | | |
| 99 | Type "ADD Garri 2500, Rice 63000, Sugar 4000" (batch) | "Added 3 products" with list | | |
| 100 | Type "ADD" with no product | Prompt: "Type the product name and price" | | |

### 8.2 Remove Products

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 101 | Type "REMOVE Milo" | "Removed Milo" | | |
| 102 | Type "REMOVE Garri, Sugar" (batch) | "Removed 2 products" | | |
| 103 | Type "REMOVE NonExistentProduct" | "Could not find NonExistentProduct" | | |

### 8.3 Update Prices

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 104 | Type "PRICE Rice 75000" | "Rice price updated: N63,000 -> N75,000" | | |
| 105 | Type "PRICE Rice 75000, Garri 3000" (batch) | "Updated 2 prices" | | |
| 106 | Type "CATALOGUE" | Full catalogue displayed as interactive picker | | |
| 107 | Tap a product in the catalogue picker | "Type the new price" prompt | | |

### 8.4 Pricelist Upload

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 108 | Type "PRICELIST" | Prompt: "Send photos of your price list" with Done button | | |
| 109 | Send 1-3 photos of a price list | Each acknowledged with count. Tap Done | | |
| 110 | After Done: products extracted and shown | "I found X products" with Update/Cancel buttons | | |
| 111 | Tap "Update catalogue" | Catalogue updated, count shown | | |

### 8.5 Product Photos

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 112 | Send a photo with caption matching a product name | "Photo saved for {product}" | | |
| 113 | Send a photo with no caption | "Which product is this for?" list picker | | |
| 114 | Tap a product in the picker | Photo saved for that product | | |

---

## Journey 9: Dashboard (Browser)

**Persona:** Trader viewing their business dashboard

### 9.1 Login & Overview

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 115 | Log in to dashboard | Greeting + KPI cards: orders, revenue, conversations, debts | | |
| 116 | Check revenue trend chart | Bar chart showing last 8 weeks | | |
| 117 | Check Today's Focus panel | Action items (if any) | | |

### 9.2 Orders Page

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 118 | Navigate to /orders | Orders table with all orders | | |
| 119 | Check status badges | Inquiry/Confirmed/Paid/Completed/Cancelled badges visible | | |
| 120 | Check "Awaiting Payment" badge on confirmed non-credit order | Outline badge shown next to Confirmed | | |
| 121 | Check "Credit" badge on credit order | Warning badge shown | | |
| 122 | Use status filter tabs | Counts update, table filters correctly | | |
| 123 | Search by customer name | Table filters by name | | |
| 124 | Click Confirm on an inquiry order | Status changes to Confirmed | | |
| 125 | Click Paid on a confirmed order | Status changes to Paid | | |
| 126 | Click Cancel on an inquiry order | Status changes to Cancelled | | |

### 9.3 Catalogue Page

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 127 | Navigate to /catalogue | Products table with names, prices, photo column | | |
| 128 | Edit a price inline | Price updates | | |
| 129 | Upload a product photo | Thumbnail appears in photo column | | |
| 130 | Replace an existing photo | New thumbnail replaces old | | |

### 9.4 Reports Page

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 131 | Navigate to /reports | Report history table (or empty state) | | |
| 132 | Click a report row | Modal opens with full report text | | |
| 133 | Check status badges | Sent (green), Failed (red), Skipped (grey) | | |

### 9.5 Settings

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 134 | Navigate to /settings | Weekly report card visible | | |
| 135 | Toggle weekly reports ON | Saved | | |
| 136 | Enter recipient phone | Saved | | |
| 137 | Click "Send preview now" | Preview sent to WhatsApp, success message shown | | |

### 9.6 Dark Mode

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 138 | Toggle dark mode | All pages render correctly — no white flashes, readable text | | |
| 139 | Check validation colors in dark mode | Error text visible (not white-on-white) | | |

### 9.7 Mobile Responsive

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 140 | Open dashboard on mobile (or resize to 375px) | Sidebar collapses to hamburger, tables scroll horizontally | | |
| 141 | Check store page on mobile | Full width, sticky order bar usable | | |

---

## Journey 10: Automated Jobs

**Persona:** System (scheduler)

### 10.1 Weekly Report

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 142 | Enable reports + set recipient, trigger via POST /reports/trigger-weekly | Report sent to WhatsApp, row appears in weekly_reports table | | |
| 143 | Trigger again for the same week | Idempotent — no duplicate send | | |
| 144 | Check report content | Includes: leads, orders, revenue, WoW delta, top customers, needs attention, debt summary, trending products | | |

### 10.2 Status Kit

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 145 | Trader has products with photos | Daily at 6:30am WAT: 2-3 Status cards sent | | |
| 146 | Trader has products WITHOUT photos | Text-only gradient cards generated | | |
| 147 | Check card design | 1080x1920, product name, price, store link, CTA | | |

### 10.3 Order Reminders

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 148 | Leave an inquiry unconfirmed for 1h+ | Trader gets reminder (business hours only) | | |
| 149 | Reminder should not fire twice for the same order | Check reminder_sent_at is set | | |

### 10.4 Debt Reminders

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 150 | Active debt older than 3 days | Customer gets gentle reminder (business hours only) | | |
| 151 | Trader gets notification that reminder was sent | "I sent a friendly reminder to {name}" | | |

---

## Journey 11: Bank Details & Verification

**Persona:** Trader setting up bank account

### 11.1 Bank Setup

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 152 | Type "BANK" | Current bank details shown (or "not set" prompt) | | |
| 153 | Type "GTBank 0123456789" | Paystack resolves account name, shows "Is this correct?" with Yes/No buttons | | |
| 154 | Tap "Yes, save it" | Bank details saved, confirmation shown | | |
| 155 | Tap "No, re-enter" | "Type your bank name and account number again" | | |

### 11.2 Unknown Bank

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 156 | Type "FakeBank 1234567890" | "I don't recognise FakeBank" — asks to re-enter | | |

### 11.3 Paystack Unavailable

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 157 | Set PAYSTACK_SECRET_KEY to empty, type "GTBank 0123456789" | Fallback: saves with business name, shows "couldn't verify" message | | |

---

## Edge Cases & Stress Tests

### Message Noise

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 158 | Trader receives a personal message from a friend (not a customer) | Silent fallback — menu shown (trader is always treated as trader) | | |
| 159 | Send only emojis: "👍👍👍" | Filtered out, no response | | |
| 160 | Send a very long message (500+ chars) | Parsed without error, Claude handles it | | |

### Concurrent Operations

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 161 | Two customers send product photos simultaneously to the same trader | Both inquiries stored separately (per-customer Redis keys) | | |
| 162 | Customer sends order while another customer is negotiating | Both handled independently | | |
| 163 | Customer sends "paid" while trader is processing another order | Payment detected for the correct confirmed order | | |

### WhatsApp Limits

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 164 | Trader with 11+ products in catalogue: check MENU list | Max 10 rows — no WhatsApp error | | |
| 165 | Check all interactive messages have <= 3 buttons | No WhatsApp API errors | | |
| 166 | Check list messages have <= 10 rows per section | No WhatsApp API errors | | |

### Data Integrity

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 167 | Create order via WhatsApp, check it appears on dashboard | Same order ID, same amount, same customer | | |
| 168 | Update price via WhatsApp, check catalogue page on dashboard | Price matches | | |
| 169 | Add bank details via WhatsApp, check store page shows them | Bank details match | | |
| 170 | Mark order PAID via WhatsApp, check orders page status | Shows "Paid" badge | | |

### Error Recovery

| # | Step | Expected | Status | Notes |
|---|------|----------|--------|-------|
| 171 | Send a message while Redis is down | Graceful error (not a crash), message may be lost but system recovers | | |
| 172 | Send a message while PostgreSQL is down | 500 error but no data corruption after recovery | | |
| 173 | Send a photo while R2 credentials are wrong | "I couldn't process that photo" fallback | | |

---

## Test Summary

| Journey | Total Tests | Pass | Fail | Blocked | Skipped |
|---------|------------|------|------|---------|---------|
| 1. Onboarding | 17 | | | | |
| 2. Store Page | 18 | | | | |
| 3. Customer Order | 16 | | | | |
| 4. Trader Management | 12 | | | | |
| 5. Payment Flow | 12 | | | | |
| 6. Negotiation | 8 | | | | |
| 7. Debt Tracker | 12 | | | | |
| 8. Catalogue Mgmt | 17 | | | | |
| 9. Dashboard | 27 | | | | |
| 10. Automated Jobs | 10 | | | | |
| 11. Bank Details | 6 | | | | |
| Edge Cases | 16 | | | | |
| **TOTAL** | **173** | | | | |

---

## Bug Tracker

| # | Journey | Test # | Description | Severity | Fixed? |
|---|---------|--------|-------------|----------|--------|
| | | | | | |
