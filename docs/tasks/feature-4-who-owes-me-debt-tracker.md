# Feature 4: Who Owes Me — Debt Tracker — Task Tracker

## Overview

Logs debts from credit sales, sends weekly Friday summaries, and warm reminders.
Design rule: never send aggressive debt reminders — always warm, respectful, no deadlines.

## Done

| # | Task | Description |
|---|------|-------------|
| ✅ | Database model | CreditSale model with statuses: ACTIVE, SETTLED, DISPUTED, WRITTEN_OFF. Fields: amount, currency, due_date, customer_name, reminder tracking (interval, max, sent count, last_reminded_at). Indexes on (tenant_id, status) and conversation_id. |
| ✅ | Migration | `010_add_credit_sales.py` — creates credit_sales table with all columns, constraints, unique order_id |
| ✅ | Repository layer | Full CRUD: create, get_by_id (tenant-scoped), get_by_order_id, list (with status filter), update_status, increment_reminder |
| ✅ | Service layer | create_credit_sale (idempotent), list, get, settle, dispute, write_off — all emit `credit_sale.status_changed` events. send_reminder with safety checks (active status, max_reminders, conversation link) |
| ✅ | REST API | `GET /credit-sales` (list + filter), `POST /credit-sales/` (create), `GET /credit-sales/{id}`, `POST /{id}/settle`, `POST /{id}/dispute`, `POST /{id}/write-off`, `POST /{id}/remind` |
| ✅ | Order integration | Event listener for `credit_sale.status_changed` — when SETTLED or WRITTEN_OFF, auto-transitions linked order to COMPLETED |
| ✅ | Module registration | Router registered in main.py, credit_sale.status_changed handler registered at startup |
| ✅ | Pydantic schemas | CreditSaleCreate, CreditSaleOut, CreditSaleListResponse with proper validation |

## Not Done (MVP)

| # | Task | Description | Priority |
|---|------|-------------|----------|
| ⬜ | DEBT WhatsApp command | `DEBT [name] [amount]` — creates a credit sale via WhatsApp. Needs: Layer 1 regex in nlp.py, intent handler in service.py, WhatsApp response template. | High |
| ⬜ | PAID WhatsApp command | `PAID [name] [amount]` — settles a debt via WhatsApp. Needs to fuzzy-match debtor name, settle the credit sale, confirm to trader. | High |
| ⬜ | WHO OWES ME command | Formatted list of all active debts: name, amount, date. Paginated if >10. Should show total outstanding at the bottom. | High |
| ⬜ | Automated reminder scheduler | Background job (APScheduler) that checks active credit sales past reminder_interval_days and sends warm reminders. Currently manual-only via API. | High |
| ⬜ | Friday debt summary in weekly report | Extend `_gather_metrics()` + `render_report()` in reports service to include: total outstanding, debts settled this week, top debtors. | Medium |
| ⬜ | Dashboard credit sales endpoints | Add debt summary to dashboard metrics: total outstanding, overdue count, recently settled. Currently dashboard has no credit data. | Medium |

## Nice to Have (Post-MVP)

| # | Task | Description |
|---|------|-------------|
| ⬜ | Overdue debt alerts in Today's Focus | Dashboard "Today's Focus" panel should include debts past due_date as urgent items |
| ⬜ | Reminder escalation levels | Gentle → firm → final notice templates instead of one generic reminder |
| ⬜ | Dispute/write-off notes | Capture reason text when disputing or writing off a debt for audit trail |
| ⬜ | Partial payments | `PAID [name] [partial amount]` — reduce debt amount instead of fully settling |
| ⬜ | Debt history per customer | Show full payment/debt history for a customer across all transactions |
| ⬜ | Batch debt entry | `DEBT Iya Bimpe 5000, Mama Tayo 3000, Bro Femi 8000` — multiple debts in one message |
| ⬜ | WhatsApp interactive debt list | WHO OWES ME returns a list picker where trader can tap a name to settle or remind |
| ⬜ | Customer debt notification | When a debt is created, optionally notify the customer: "You have a balance of N5,000 with {trader}" |
| ⬜ | Debt aging report | Group debts by age: <7 days, 7-30 days, >30 days with totals per bucket |
| ⬜ | Auto-create from credit orders | When an order is marked CONFIRMED but not PAID within X days, auto-create a credit sale |

## Key Files

| File | Purpose |
|------|---------|
| `app/modules/credit_sales/models.py` | CreditSale + CreditSaleStatus ORM model |
| `app/modules/credit_sales/repository.py` | Database queries (CRUD + status transitions + reminder tracking) |
| `app/modules/credit_sales/service.py` | Business logic, event publishing, reminder sending |
| `app/modules/credit_sales/router.py` | REST API endpoints |
| `app/modules/credit_sales/schemas.py` | Pydantic request/response schemas |
| `alembic/versions/010_add_credit_sales.py` | Database migration |
| `app/modules/orders/handlers.py` | credit_sale.status_changed event listener (auto-completes orders) |

## Design Notes

- Trader always has final say — no automated debt settlement
- Reminders are warm and respectful: "Just a gentle reminder about your balance"
- No deadlines or threats in reminder messages
- Maximum 5 reminders per debt (configurable, max 20)
- Minimum 3 days between reminders (configurable, max 30)
- One credit sale per order (unique constraint on order_id)
- Settled/written-off debts auto-complete the linked order via event bus
