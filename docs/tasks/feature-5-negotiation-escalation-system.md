# Feature 5: Negotiation Escalation System — Task Tracker

## Overview

Detects when a customer is negotiating on price (e.g. "can you do 7000?", "too expensive", "last price"), holds the conversation, and alerts the trader to respond with a counter-offer or accept/decline. The trader always has final say on pricing — the system never auto-accepts or auto-declines.

## Done

Nothing built yet. Feature 5 is entirely planned.

## Not Done (MVP)

| # | Task | Description | Priority |
|---|------|-------------|----------|
| ⬜ | NLP negotiation detection | Layer 1 regex patterns to detect negotiation language: "too expensive", "reduce", "discount", "last price", "can you do X", "cheaper", "what's your best price", "na better price", Nigerian Pidgin haggling phrases. Return `NEGOTIATION` intent with extracted offer price if present. | High |
| ⬜ | Claude negotiation detection (Layer 2) | Add negotiation intent to Claude Haiku prompt so ambiguous messages like "that's too much for this" get classified correctly. | High |
| ⬜ | Negotiation session state | Redis states: `AWAITING_TRADER_NEGOTIATION` — customer is held while trader decides. Store: customer_phone, original_price, offered_price, product_name, order context. | High |
| ⬜ | Customer hold message | When negotiation detected, reply to customer: "Let me check with the trader about that price. One moment!" Prevents customer from placing order at the wrong price. | High |
| ⬜ | Trader escalation notification | Send trader an interactive message: "Customer +234... wants {product} at N7,000 (your price: N8,500). [Accept] [Counter-offer] [Decline]" | High |
| ⬜ | Trader Accept flow | Trader taps Accept → update the order price to customer's offer → notify customer: "Great news! The trader accepted N7,000." → resume order flow | High |
| ⬜ | Trader Decline flow | Trader taps Decline → notify customer: "Sorry, the trader can't go below N8,500 for this item." → customer can accept original price or cancel | High |
| ⬜ | Trader Counter-offer flow | Trader taps Counter-offer → session state: `AWAITING_COUNTER_PRICE` → trader types a price → notify customer: "The trader can do N7,500. Would you like to proceed?" → customer YES/NO | Medium |
| ⬜ | WhatsApp message templates | Templates for: hold message, escalation to trader, accept/decline/counter notifications, counter-offer prompt | High |
| ⬜ | Session timeout | If trader doesn't respond within 30 minutes, auto-notify customer: "The trader hasn't responded yet. You can try again later or accept the listed price." Clear session. | Medium |

## Nice to Have (Post-MVP)

| # | Task | Description |
|---|------|-------------|
| ⬜ | Multi-round negotiation | Customer can counter the counter-offer. Support back-and-forth until agreement or one side walks away. |
| ⬜ | Auto-accept threshold | Trader sets a minimum acceptable discount (e.g. "accept anything above 10% off"). System auto-accepts offers within threshold without bothering the trader. |
| ⬜ | Negotiation history | Track all negotiations per customer: original price, offered price, final price, outcome. Show in dashboard. |
| ⬜ | Dashboard negotiation panel | Live view of pending negotiations in Today's Focus. Trader can respond from the web dashboard, not just WhatsApp. |
| ⬜ | Price negotiation analytics | Track: how often customers negotiate, average discount given, which products get negotiated most, conversion rate after negotiation. |
| ⬜ | Bulk pricing rules | Trader sets rules: "10+ cartons = 5% off", "wholesale price for orders above N100,000". System auto-applies without escalation. |
| ⬜ | Negotiation language learning | Claude learns which phrases indicate negotiation for this specific trader's customer base over time. |
| ⬜ | Group negotiation | When ChatToSales is in a group, detect negotiation from any member and escalate privately to trader. |
| ⬜ | Negotiation templates for trader | Pre-set responses: "I can do 5% off", "Final price, no discount", "Buy 2 and I'll reduce". Trader taps instead of typing. |

## Key Design Rules

- **Trader always has final say** — system never accepts or declines on their behalf (unless auto-accept threshold is set in post-MVP)
- **Customer is always informed** — never left waiting without acknowledgment
- **Warm tone** — "Let me check with the trader" not "Your offer is being reviewed"
- **Fast escalation** — trader gets the notification within seconds, not batched
- **No aggressive follow-up** — if trader doesn't respond, customer is gently informed and can move on
- **Works with existing order flow** — negotiation is a pause in the order conversation, not a separate system

## Architecture Notes

| Component | Location | What to add |
|-----------|----------|-------------|
| NLP detection | `app/modules/orders/nlp.py` | `NEGOTIATION` intent + regex patterns + Claude prompt update |
| Session management | `app/modules/orders/session.py` | `AWAITING_TRADER_NEGOTIATION`, `AWAITING_COUNTER_PRICE` states + negotiation session data |
| Service logic | `app/modules/orders/service.py` | Detect negotiation in `handle_inbound_customer_message`, hold customer, escalate to trader, handle trader response |
| WhatsApp templates | `app/modules/orders/whatsapp.py` | ~8 new templates for negotiation flow |
| Handler routing | `app/modules/orders/handlers.py` | No changes needed — negotiation flows through existing trader command routing |
| Database | No new models | Negotiation state lives in Redis (short-lived). No persistent model needed for MVP. |

## Flow Diagram

```
Customer: "Can you do 7000 for the Indomie?"
    ↓
NLP detects NEGOTIATION intent (offered_price=7000, product=Indomie)
    ↓
Bot → Customer: "Let me check with the trader about that price. One moment!"
    ↓
Bot → Trader: "Customer wants Indomie at N7,000 (your price: N8,500)"
              [Accept N7,000] [Counter-offer] [Decline]
    ↓
Option A: Trader taps Accept
    → Bot → Customer: "Great news! The trader accepted N7,000. Confirm your order?"
    → Resume normal order flow at N7,000

Option B: Trader taps Decline
    → Bot → Customer: "The trader can't go below N8,500. Would you like to order at N8,500?"
    → Customer YES → normal order flow at N8,500
    → Customer NO → order cancelled

Option C: Trader taps Counter-offer → types "7500"
    → Bot → Customer: "The trader can do N7,500. Would you like to proceed?"
    → Customer YES → normal order flow at N7,500
    → Customer NO → order cancelled

Option D: 30 min timeout
    → Bot → Customer: "The trader hasn't responded yet. You can accept N8,500 or try again later."
```
