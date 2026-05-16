# Segmented Broadcast System — How It Works

## Overview

Traders send targeted WhatsApp broadcasts to their customers. The system auto-segments customers by behaviour, interests, and timing. Anti-spam protection prevents WhatsApp flagging.

## Broadcast Flow

1. Trader types **BROADCAST** or taps Marketing → Broadcast Message
2. System shows **segment picker** with customer counts
3. Trader picks a segment (e.g. "VIP Customers", "Weekend Shoppers")
4. Anti-spam checks run:
   - **48h segment cooldown**: Can't blast same segment twice in 48 hours
   - **7-day skip warning**: Shows how many customers will be skipped (already messaged <7 days ago)
   - **100+ audience warning**: Extra confirmation for large broadcasts
5. Trader types their message
6. **Quality check** blocks: ALL CAPS, 2+ exclamation marks, link shorteners (bit.ly), spam phrases
7. **Claude Haiku** rewrites the message into warm Nigerian English + adds store link
8. Trader sees preview with Send/Cancel buttons
9. On confirm: broadcast created in DB, **background task** sends messages at ~2/sec
10. Trader gets progress updates every 5 messages + completion summary

## Customer List

Customers are **auto-added** when an order is marked as PAID. The `_do_paid_transition()` method in `service.py` calls `CustomerListService.upsert_customer()`.

**Important**: ALL code paths that transition an order to PAID must go through `_do_paid_transition()`, not `_transition()` directly. This ensures the customer list stays populated.

Stored per customer: `trader_phone`, `customer_phone`, `customer_name`, `total_orders`, `total_spend`, `first_order_date`, `last_order_date`, `opted_out`, `last_broadcast_at`, `segments` (JSONB).

## Segments

### How Segments Are Computed

Segments are stored as a JSONB array on `CustomerListEntry.segments` (e.g. `["vip", "weekend", "premium"]`).

**Recomputed nightly** at 2:00 UTC (3:00 AM WAT) by the APScheduler job `_recompute_customer_segments` in `scheduler.py`. The job calls `recompute_all_segments()` in `segments.py`.

**Fallback**: Before the first nightly run, the system uses order-count heuristics (vip/repeat_buyer/paid_once/new_lead).

### Behaviour Segments (mutually exclusive — one per customer)

| Segment | Rule |
|---------|------|
| `new_lead` | 0 paid orders, no abandoned cart |
| `browsed_only` | Messaged but never ordered |
| `abandoned_cart` | Has confirmed but never-paid orders |
| `paid_once` | Exactly 1 paid order |
| `repeat_buyer` | 2-4 paid orders |
| `vip` | 5+ orders OR N200,000+ lifetime spend |
| `lapsed` | Any of above but no order in 90+ days |

### Interest Segments (additive — customer can have multiple)

| Segment | Rule |
|---------|------|
| `diverse_buyer` | Bought 5+ different products |
| `price_sensitive` | Negotiated price 2+ times |
| `premium` | 1.5x above trader's average order value, never negotiated |

### Timing Segments (additive — customer can have multiple)

| Segment | Rule | Minimum Data |
|---------|------|-------------|
| `weekly` | Average order interval <10 days | 2+ orders |
| `monthly` | Average order interval <40 days | 2+ orders |
| `payday` | >50% of orders on 25th-5th of month | 2+ orders |
| `weekend` | >60% of orders on Fri-Sun | 2+ orders |

### When Segments Appear in the Picker

Segments only appear if **count > 0**. With 1 customer who has 2 orders, you'll see:
- All Customers (1)
- Repeat Buyers (1)

As customers accumulate orders over time, more segments appear automatically after the nightly recompute.

## Anti-Spam Protection

| Protection | How It Works |
|-----------|-------------|
| 7-day per-customer cap | Each customer receives max 1 broadcast per 7 days. Enforced in paced sender + shown as skip count before composing. |
| 48-hour per-segment cap | Same segment can't be targeted within 48 hours of last broadcast to it. |
| 100+ audience warning | Extra "Are you sure?" confirmation for large broadcasts. |
| Quality check | Blocks ALL CAPS (20+ chars), 2+ exclamation marks, link shorteners, spam phrases ("guaranteed", "best price ever", "act now"). |
| STOP opt-out | Customer replies STOP → permanently opted out. Processed in `handle_inbound_customer_message`. |
| Paced sending | ~2 messages/second (500ms delay) to avoid WhatsApp rate limits. |

## Key Files

| File | Purpose |
|------|---------|
| `app/modules/marketing/models.py` | CustomerListEntry, Broadcast, BroadcastRecipient models |
| `app/modules/marketing/customer_list.py` | CustomerListService — upsert, opt_out, segment queries |
| `app/modules/marketing/segments.py` | Segment computation engine (behaviour, interest, timing) |
| `app/modules/marketing/broadcast.py` | Quality checks, Claude rewrite, paced sender, anti-spam helpers |
| `app/modules/orders/service.py` | Broadcast flow handlers (_start_broadcast_flow, _handle_broadcast_*) |
| `app/modules/orders/whatsapp.py` | WhatsApp templates for broadcast UI |
| `app/modules/orders/nlp.py` | TRADER_BROADCAST intent detection |
| `app/modules/orders/session.py` | Broadcast session states (TRADER_AWAITING_BROADCAST_*) |
| `app/infra/scheduler.py` | Nightly segment recompute job |
| `alembic/versions/030_add_marketing_tables.py` | Migration: customer_list, broadcasts, broadcast_recipients |
| `alembic/versions/031_add_customer_segments.py` | Migration: segments JSONB + segments_updated_at |

## Common Gotchas

1. **"No customers" after paid order**: Make sure the PAID transition uses `_do_paid_transition()`, not `_transition()` directly.
2. **Segments not showing**: Nightly recompute hasn't run yet. Fallback shows basic segments from order counts.
3. **48h cooldown blocking test broadcasts**: Wait 48h or use a different segment for testing.
4. **Migration 031 fails**: Ensure `down_revision` matches `"030_add_marketing_tables"` (full ID, not just `"030"`).
