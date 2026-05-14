# ChatToSales — Unit Test Plan

## Overview

Three-layer test strategy to prevent regressions. Each layer builds on the previous one.

## Directory Structure

```
tests/
  conftest.py                  — shared fixtures (mock DB, Redis, trader, customer)
  unit/
    test_nlp.py                — intent detection, regex patterns
    test_whatsapp.py           — template output, customer name fallback
    test_state_machine.py      — valid/invalid transitions
    test_session.py            — routing TTL, quiet mode, clarification context
  service/
    conftest.py                — async DB/Redis fixtures
    test_order_lifecycle.py    — create, confirm, paid, credit
    test_payment.py            — payment detection, PAYRCVD, partial payments
    test_clarification.py      — numbered list extraction, quick-pick, cancel-repick
    test_routing.py            — Redis routing, DB fallback, persistent routing
    test_catalogue.py          — add, remove, price update, pricelist
    test_debt.py               — debt creation, settlement, partial payment
  integration/
    conftest.py                — FastAPI test client, real DB/Redis
    test_handler_flow.py       — full webhook -> handler -> response
    test_onboarding_flow.py    — onboarding state machine end-to-end
    test_dashboard_api.py      — dashboard endpoints, revenue trend
```

## Framework

- pytest + pytest-asyncio
- unittest.mock for DB/Redis mocking in service tests
- httpx.AsyncClient for integration tests

---

## Layer 1: Unit Tests (Pure Functions, No External Services)

### Status: PENDING

### 1.1 test_nlp.py — Intent Detection

| # | Test Case | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_confirm_yes_variants` | "yes", "yep", "ok", "oya", "correct" all return CONFIRM |
| 2 | `test_cancel_no_variants` | "no", "nope", "cancel", "forget am" all return CANCEL |
| 3 | `test_trader_confirm_command` | "CONFIRM abc123de" returns TRADER_CONFIRM with ref |
| 4 | `test_trader_cancel_command` | "CANCEL abc123de" returns TRADER_CANCEL with ref |
| 5 | `test_trader_paid_command` | "PAID abc123de" returns TRADER_PAID with ref |
| 6 | `test_trader_credit_command` | "CREDIT abc123de" returns TRADER_CREDIT with ref |
| 7 | `test_delivered_command_removed` | "DELIVERED abc123de" does NOT return TRADER_DELIVERED (removed) |
| 8 | `test_add_single_product` | "ADD Milo 3500" returns TRADER_ADD with items |
| 9 | `test_add_batch_products` | "ADD Milo 3500, Garri 2500" returns TRADER_ADD with 2 items |
| 10 | `test_add_comma_in_price` | "ADD Milo 3,500, Garri 2,500" handles comma-in-number correctly |
| 11 | `test_remove_single` | "REMOVE Garri" returns TRADER_REMOVE |
| 12 | `test_remove_batch` | "REMOVE Garri, Milo" returns TRADER_REMOVE with 2 items |
| 13 | `test_price_update` | "PRICE Rice 75000" returns TRADER_PRICE |
| 14 | `test_price_batch` | "PRICE Rice 75000, Milo 4000" returns TRADER_PRICE with 2 items |
| 15 | `test_catalogue_command` | "CATALOGUE" returns TRADER_CATALOGUE |
| 16 | `test_menu_command` | "MENU" returns TRADER_MENU |
| 17 | `test_bank_command` | "BANK" returns TRADER_BANK |
| 18 | `test_orders_command` | "ORDERS" returns TRADER_ORDERS |
| 19 | `test_who_owes_me` | "WHO OWES ME" returns TRADER_WHO_OWES_ME |
| 20 | `test_debt_command` | "DEBT Iya Bimpe 5000" returns TRADER_DEBT with name + amount |
| 21 | `test_paid_debt_command` | "PAID Iya Bimpe 5000" returns TRADER_PAID_DEBT (name starts with letter) |
| 22 | `test_payment_sent_paid` | "paid" returns PAYMENT_SENT |
| 23 | `test_payment_sent_ive_paid` | "I've paid" returns PAYMENT_SENT |
| 24 | `test_payment_sent_transferred` | "transferred" returns PAYMENT_SENT |
| 25 | `test_payment_sent_sent` | "sent" returns PAYMENT_SENT |
| 26 | `test_payment_sent_check_account` | "check your account" returns PAYMENT_SENT |
| 27 | `test_payment_sent_pidgin` | "e don pay" returns PAYMENT_SENT |
| 28 | `test_negotiation_specific_price` | "can you do 5000?" returns NEGOTIATION with offered_price=5000 |
| 29 | `test_negotiation_general` | "too expensive" returns NEGOTIATION |
| 30 | `test_negotiation_discount` | "any discount?" returns NEGOTIATION |
| 31 | `test_order_intent_with_items` | "2 bags of rice" returns ORDER with items |
| 32 | `test_order_intent_keywords_only` | "I want to buy" returns ORDER with confidence 0.3 |
| 33 | `test_unknown_random_text` | "pick up the kids" returns UNKNOWN |
| 34 | `test_pricelist_command` | "PRICE LIST" returns TRADER_PRICELIST |
| 35 | `test_category_command` | "CATEGORY" returns TRADER_CATEGORY |
| 36 | `test_yoruba_numbers` | "meji bags of rice" → qty=2 |
| 37 | `test_case_insensitive` | "confirm ABC123DE" matches same as "CONFIRM abc123de" |

### 1.2 test_state_machine.py — Order State Transitions

| # | Test Case | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_inquiry_to_confirmed` | INQUIRY → CONFIRMED is valid |
| 2 | `test_inquiry_to_failed` | INQUIRY → FAILED is valid |
| 3 | `test_confirmed_to_paid` | CONFIRMED → PAID is valid |
| 4 | `test_confirmed_to_failed` | CONFIRMED → FAILED is valid |
| 5 | `test_paid_is_terminal` | PAID → anything raises InvalidTransitionError |
| 6 | `test_failed_is_terminal` | FAILED → anything raises InvalidTransitionError |
| 7 | `test_skip_state_rejected` | INQUIRY → PAID raises InvalidTransitionError |
| 8 | `test_same_state_rejected` | CONFIRMED → CONFIRMED raises InvalidTransitionError |
| 9 | `test_completed_not_in_enum` | OrderState has no COMPLETED member |
| 10 | `test_invalid_state_string` | Unknown state string raises InvalidTransitionError |

### 1.3 test_whatsapp.py — Template Output

| # | Test Case | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_customer_label_with_name` | _customer_label("Sodiq", "234...") returns "*Sodiq*" |
| 2 | `test_customer_label_no_name` | _customer_label(None, "234...") returns "+234..." |
| 3 | `test_order_confirmed_with_name` | order_confirmed_to_trader shows customer name, not phone |
| 4 | `test_order_confirmed_no_name` | order_confirmed_to_trader falls back to phone |
| 5 | `test_order_cancelled_with_name` | Shows "*Sodiq*'s order cancelled" |
| 6 | `test_order_paid_with_name` | Shows "*Sodiq*'s" not order ref |
| 7 | `test_order_credit_with_name` | Shows "*Sodiq*'s order marked as credit" |
| 8 | `test_credit_buttons_format` | order_credit_buttons returns Paid in Full + Partial Payment |
| 9 | `test_already_on_credit_with_name` | Shows name, not ref |
| 10 | `test_credit_partial_prompt_with_name` | Shows "*Sodiq* — outstanding: N770,000" |
| 11 | `test_credit_paid_in_full_with_name` | Shows "*Sodiq* fully paid!" |
| 12 | `test_credit_partial_received_with_name` | Shows "Received N50,000 from *Sodiq*" |
| 13 | `test_payment_receipt_to_trader` | Shows customer name and amount with buttons |
| 14 | `test_payment_receipt_with_screenshot` | Includes "screenshot" text when has_screenshot=True |
| 15 | `test_pending_order_actions_non_credit` | Returns Paid + Credit buttons |
| 16 | `test_pending_order_actions_credit` | Returns Paid in Full + Partial Payment buttons |
| 17 | `test_order_action_buttons_inquiry` | Returns Confirm + Cancel buttons |
| 18 | `test_order_action_buttons_confirmed_credit` | Returns Paid in Full + Partial Payment |
| 19 | `test_order_action_buttons_paid_no_buttons` | PAID state returns no buttons (terminal) |
| 20 | `test_bank_verify_confirm_format` | Shows bank name, account, resolved name with Yes/No |
| 21 | `test_naira_formatting` | _naira(850000) returns "N850,000" |
| 22 | `test_order_reminder_with_name` | Shows customer name not phone |

### 1.4 test_session.py — Redis Session Logic

| # | Test Case | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_routing_ttl_is_7_days` | _CUSTOMER_ROUTING_TTL == 7 * 24 * 60 * 60 |
| 2 | `test_quiet_mode_ttl_is_30_min` | _QUIET_TTL == 30 * 60 |
| 3 | `test_session_ttl_is_24h` | _SESSION_TTL == 24 * 60 * 60 |
| 4 | `test_last_clarify_ttl_is_10_min` | _LAST_CLARIFY_TTL == 10 * 60 |
| 5 | `test_session_state_constants` | All AWAITING_* constants are unique strings |
| 6 | `test_trader_session_states` | TRADER_AWAITING_* constants exist and are unique |

---

## Layer 2: Service Tests (Mock DB + Redis)

### Status: PENDING

### 2.1 test_order_lifecycle.py

| # | Test Case | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_create_inquiry_order` | Order created with INQUIRY state, correct customer info |
| 2 | `test_confirm_order` | INQUIRY → CONFIRMED, customer notified with bank details |
| 3 | `test_pay_order` | CONFIRMED → PAID (terminal) |
| 4 | `test_cancel_inquiry` | INQUIRY → FAILED |
| 5 | `test_cancel_confirmed` | CONFIRMED → FAILED |
| 6 | `test_cannot_pay_inquiry` | INQUIRY → PAID rejected |
| 7 | `test_cannot_modify_paid` | PAID → anything rejected |
| 8 | `test_customer_name_stored` | Order preserves customer_name from creation |

### 2.2 test_payment.py

| # | Test Case | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_payment_sent_finds_confirmed_order` | Customer "paid" matches their CONFIRMED order |
| 2 | `test_payment_sent_no_confirmed_order` | "paid" with no order shows "no confirmed order" |
| 3 | `test_payment_sent_breaks_quiet_mode` | "paid" during quiet mode still processes |
| 4 | `test_payrcvd_marks_paid` | Trader taps Payment Received → order PAID |
| 5 | `test_paynotrcvd_notifies_customer` | Trader taps Not Received → customer notified |
| 6 | `test_image_with_confirmed_order_is_receipt` | Image during confirmed order → payment screenshot |
| 7 | `test_image_without_confirmed_order_is_inquiry` | Image without order → product inquiry |

### 2.3 test_clarification.py

| # | Test Case | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_numbered_list_extraction_dash_N` | "1. Product - N330,000" extracted correctly |
| 2 | `test_numbered_list_extraction_colon_naira` | "1. Product: ₦330,000" extracted correctly |
| 3 | `test_numbered_list_extraction_multiple` | 5 items extracted from multi-line list |
| 4 | `test_quick_pick_by_number` | Customer types "3" → picks item #3 |
| 5 | `test_quick_pick_invalid_number` | Customer types "99" with 3-item list → falls to Claude |
| 6 | `test_cancel_restores_clarification` | Cancel after order → clarification session restored |
| 7 | `test_cancel_without_clarification` | Cancel with no previous list → normal cancel |
| 8 | `test_bot_reply_stored_in_session` | Clarification saves bot_reply to session |
| 9 | `test_context_passed_to_claude` | extra_history includes original + bot_reply |

### 2.4 test_routing.py

| # | Test Case | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_order_slug_creates_routing` | ORDER:{slug} creates Redis + DB routing |
| 2 | `test_redis_routing_used_first` | Existing Redis routing skips DB lookup |
| 3 | `test_db_fallback_when_redis_expired` | No Redis → DB lookup → routing restored |
| 4 | `test_no_routing_shows_store_prompt` | No Redis, no DB → "visit store link" |
| 5 | `test_new_slug_overwrites_routing` | ORDER:new-store overwrites previous routing |
| 6 | `test_persistent_routing_upsert` | Second order from same customer updates DB row |

### 2.5 test_catalogue.py

| # | Test Case | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_add_single_product` | ADD command adds to catalogue |
| 2 | `test_add_batch_products` | Batch ADD adds multiple products |
| 3 | `test_remove_product` | REMOVE command removes from catalogue |
| 4 | `test_remove_nonexistent` | REMOVE unknown product shows error |
| 5 | `test_price_update` | PRICE command updates price |
| 6 | `test_price_batch` | Batch PRICE updates multiple |
| 7 | `test_zero_price_catalogue_lookup` | unit_price=0 triggers catalogue lookup |

### 2.6 test_debt.py

| # | Test Case | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_create_debt` | DEBT command creates credit sale |
| 2 | `test_settle_debt` | Settle clears debt |
| 3 | `test_partial_payment` | Partial payment reduces balance |
| 4 | `test_partial_then_full` | Partial + full settles completely |
| 5 | `test_duplicate_credit_blocked` | Second CREDIT on same order shows "already on credit" |
| 6 | `test_credit_order_shows_outstanding` | Orders list shows outstanding not original amount |
| 7 | `test_credit_paid_in_full` | CREDITPAID marks order PAID + settles credit sale |

---

## Layer 3: Integration Tests (Real DB + Redis)

### Status: PENDING

### 3.1 test_handler_flow.py

| # | Test Case | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_cart_order_full_flow` | ORDER:{slug} → summary → YES → trader notified |
| 2 | `test_freeform_order_flow` | Text → Claude → summary → confirm |
| 3 | `test_trader_confirm_cancel_paid` | Full trader command cycle |
| 4 | `test_onboarding_skips_order_handler` | Onboarding user not processed by order handler |
| 5 | `test_image_inquiry_flow` | Customer photo → trader notified → reply → customer notified |
| 6 | `test_emoji_filtered` | Pure emoji message gets no response |
| 7 | `test_quiet_mode_blocks_noise` | "thanks" after order → no response |
| 8 | `test_quiet_mode_passes_orders` | "I want rice" after order → processed |

### 3.2 test_dashboard_api.py

| # | Test Case | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_revenue_trend_returns_8_weeks` | /revenue-trend returns 8 data points |
| 2 | `test_revenue_trend_fills_gaps` | Missing weeks show zero revenue |
| 3 | `test_report_history_empty` | /reports/history returns empty for new tenant |
| 4 | `test_metrics_include_debts` | /metrics includes debt counts |

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# Just unit tests (fast, no DB needed)
pytest tests/unit/ -v

# Just service tests
pytest tests/service/ -v

# Stop on first failure
pytest tests/ -x

# With coverage
pytest tests/ --cov=app --cov-report=term-missing
```

## Test Naming Convention

```
test_{what}_{scenario}_{expected_outcome}
```

Examples:
- `test_payment_sent_during_quiet_mode_breaks_through`
- `test_duplicate_credit_returns_friendly_message`
- `test_cancel_with_numbered_list_restores_clarification`

## Bug Regression Mapping

Each bug we fixed maps to a specific test:

| Bug | Test |
|-----|------|
| Duplicate credit crash | `test_duplicate_credit_blocked` |
| Zero-price items skipping lookup | `test_zero_price_catalogue_lookup` |
| Quiet mode blocking real orders | `test_quiet_mode_passes_orders` |
| Cancel doesn't restore clarification | `test_cancel_restores_clarification` |
| COMPLETED state complexity | `test_paid_is_terminal`, `test_completed_not_in_enum` |
| Phone shown instead of name | `test_order_confirmed_with_name` |
| Onboarding path switching stuck | (manual test — WhatsApp-specific) |
