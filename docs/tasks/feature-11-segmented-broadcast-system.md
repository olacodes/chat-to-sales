# Feature 11: Segmented Broadcast System — Task Tracker

## Overview

Targeted WhatsApp broadcasts that reach the right customers without burning the trader's WhatsApp reputation. Auto-segments customers by behaviour, interests, and timing. Anti-spam protection built in. Tracks delivery, reads, replies, and orders attributed to each broadcast.

## Build Order

Phase 1 (Foundation) → Phase 3 (WhatsApp Flow) → Phase 4 (Anti-Spam) → Phase 2 (Segments) → Phase 5 (Results) → Phase 8 (Dashboard) → Phase 6 (Smart Suggestions) → Phase 7 (Templates)

## Phase 1: Foundation

| # | Task | Status |
|---|------|--------|
| 1.1 | Customer list model + auto-populate | ✅ |
| 1.2 | Opt-out handling (STOP) | ✅ |
| 1.3 | Broadcast model + recipients model | ✅ |

## Phase 2: Segments Engine

| # | Task | Status |
|---|------|--------|
| 2.1 | Behaviour segments (new_lead → vip → lapsed) | ⬜ |
| 2.2 | Interest segments (bought_X, interested_X, price_sensitive) | ⬜ |
| 2.3 | Timing segments (weekly, monthly, payday, weekend) | ⬜ |
| 2.4 | Nightly segment recompute scheduler job | ⬜ |
| 2.5 | Custom segment via DESCRIBE (Claude interprets) | ⬜ |

## Phase 3: Broadcast WhatsApp Flow

| # | Task | Status |
|---|------|--------|
| 3.1 | BROADCAST command → segment list picker | ✅ |
| 3.2 | Segment selection → count + description | ✅ |
| 3.3 | Message composition + Claude rewrite + preview | ✅ |
| 3.4 | Voice note to broadcast text (Whisper + Claude) | ⬜ |
| 3.5 | Pre-send quality check (caps, spam, links) | ✅ |
| 3.6 | Paced sending (10-30 min, individual messages) | ✅ |
| 3.7 | Background task (non-blocking) | ✅ |
| 3.8 | STOP reply processing during broadcast | ✅ |

## Phase 4: Anti-Spam Protection

| # | Task | Status |
|---|------|--------|
| 4.1 | 7-day per-customer marketing cap | ✅ |
| 4.2 | 48-hour per-segment cap | ✅ |
| 4.3 | Open rate auto-pause (<40%) | ⬜ (needs delivery webhooks) |
| 4.4 | Wide audience warning (100+ people) | ✅ |
| 4.5 | Quality rating check → pause if low | ⬜ (needs Meta webhook) |
| 4.6 | Message block list (caps, spam patterns) | ✅ |

## Phase 5: Results Tracking

| # | Task | Status |
|---|------|--------|
| 5.1 | Delivery tracking (sent → delivered → read → replied) | ⬜ |
| 5.2 | Reply routing → order flow + attribution | ⬜ |
| 5.3 | 24-hour results notification to trader | ⬜ |
| 5.4 | 48-hour results notification + "not replied" list | ⬜ |
| 5.5 | REMIND ALL follow-up command | ⬜ |
| 5.6 | Dashboard broadcast history page | ⬜ |

## Phase 6: Smart Suggestions (Alatise tier)

| # | Task | Status |
|---|------|--------|
| 6.1 | Price drop → suggest broadcast to past buyers | ⬜ |
| 6.2 | Lapsed customer → suggest nudge broadcast | ⬜ |
| 6.3 | Payday period → suggest broadcast to payday segment | ⬜ |
| 6.4 | New stock added → suggest broadcast to interested customers | ⬜ |

## Phase 7: WhatsApp Template Messages

| # | Task | Status |
|---|------|--------|
| 7.1 | Template library (50+ pre-approved templates) | ⬜ |
| 7.2 | Auto-select template for cold contacts (>24h window) | ⬜ |
| 7.3 | Template submission to Meta via API | ⬜ |

## Phase 8: Menu + Dashboard Integration

| # | Task | Status |
|---|------|--------|
| 8.1 | Marketing sub-menu → Broadcast Message | ✅ |
| 8.2 | Dashboard /broadcasts page (create, history, stats) | ⬜ |
| 8.3 | Dashboard /customers page (list, segments, history) | ⬜ |

## Anti-Spam Limits (Hard Rules)

| Limit | Rationale |
|-------|-----------|
| Max 1 marketing message per customer per 7 days | Prevents muting/blocking/reporting |
| Max 1 broadcast per segment per 48 hours | No rapid-fire to same group |
| Auto-pause if open rate < 40% | Protects WhatsApp quality rating |
| Pre-send quality check | Blocks ALL CAPS, link shorteners, spam patterns |
| Approved templates for cold contacts | Required by Meta for >24h window messages |
| Easy opt-out (STOP) | Every broadcast includes opt-out, processed automatically |
| Message block: ALL CAPS, 2+ exclamation marks, bit.ly, "Guaranteed!", "Best price ever!" | WhatsApp spam classifier patterns |

## Segment Definitions

### Behaviour Segments
| Segment | Rule |
|---------|------|
| new_lead | Messaged once, never ordered |
| browsed_only | Asked about a product, never confirmed an order |
| abandoned_cart | Confirmed an order but never paid |
| paid_once | Completed one order |
| repeat_buyer | 2-4 completed orders |
| vip | 5+ orders OR N200,000+ lifetime spend |
| lapsed | Was regular but no order in 3+ usual cycles |

### Interest Segments
| Segment | Rule |
|---------|------|
| bought_[category] | Has bought from this category |
| interested_[category] | Asked about category but didn't buy |
| price_sensitive | Negotiated price 2+ times |
| premium | Bought high-tier items without negotiating |

### Timing Segments
| Segment | Rule |
|---------|------|
| weekly | Orders ~once per week |
| monthly | Orders ~once per month |
| payday | Orders cluster around 25th-5th |
| weekend | Orders mostly Fri-Sun |

## Key Files

| File | Purpose |
|------|---------|
| `app/modules/marketing/__init__.py` | Module init |
| `app/modules/marketing/models.py` | CustomerList, Broadcast, BroadcastRecipient, CustomerSegment |
| `app/modules/marketing/customer_list.py` | Auto-populate + manage customer list |
| `app/modules/marketing/segments.py` | Segment computation engine |
| `app/modules/marketing/broadcast.py` | Broadcast service + paced sender |
| `app/modules/marketing/quality.py` | Anti-spam checks + quality gate |
| `app/modules/marketing/router.py` | Dashboard API endpoints |
| `alembic/versions/030_add_marketing_tables.py` | Migration |
