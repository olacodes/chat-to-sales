# Feature 8: Business Intelligence & Reports — Task Tracker

## Overview

Monday 8am weekly WhatsApp summary sent to the trader. Covers: new leads, orders, revenue, top customers, and items needing attention. Report is warm, actionable, and formatted for WhatsApp readability.

## Done

| # | Task | Description |
|---|------|-------------|
| ✅ | Report database models | `TenantReportConfig` (enabled, recipient_phone, timezone) + `WeeklyReport` audit log (week_start, status sent/failed/skipped, report_text, error_detail). Unique constraint on (tenant_id, week_start) for idempotency. Migration 005. |
| ✅ | Metrics gathering | Previous week, tenant-scoped: new_conversations, new_orders, revenue_paid (PAID orders only), top_customers (top 3 by order count + revenue), needs_attention (open conversations with no reply >24h). Currency default NGN. |
| ✅ | Week-over-week delta | Compares current week's conversations and revenue to prior week. Shows +12% or -8% in the report. |
| ✅ | Report formatting | WhatsApp-native format: header with date range, "at a glance" metrics, top customers section, needs attention section, footer. Warm, readable. |
| ✅ | Report service | `get_config()`, `upsert_config()`, `send_preview()` (sends immediately, no audit log), `run_weekly()` (sends + logs audit row). Deterministic UUID v5 for idempotent event IDs. Timezone-aware week boundaries (Mon 00:00 → Sun 23:59). |
| ✅ | REST API endpoints | `GET /reports/config`, `PUT /reports/config`, `POST /reports/send-preview`, `POST /reports/trigger-weekly` (protected by X-Report-Secret header). |
| ✅ | WhatsApp delivery | Sends via NotificationService → WhatsApp channel. Requires connected WhatsApp channel. Returns 400 if disconnected. |
| ✅ | Frontend config UI | WeeklyReportCard in Settings: toggle enable/disable, phone input (E.164), "Send preview now" button. Success/error messages. |
| ✅ | React hooks | `useReportConfig()`, `useUpdateReportConfig()`, `useSendPreview()`. 60s stale time. |
| ✅ | Idempotency + error handling | Same tenant+week = same event_id (no duplicate sends). Failed sends logged with error_detail. Skipped if disabled or no recipient. |
| ✅ | Configuration | REPORT_SECRET env var for trigger endpoint protection. Validated in production. |
| ✅ | Module registration | Router registered in main.py. |
| ✅ | Automatic Monday 8am scheduling | `_send_weekly_reports()` in scheduler.py: APScheduler cron job (Monday 7:00 UTC = 8:00 AM WAT). Queries all tenants with reports enabled + recipient set, calls `run_weekly()` for each. 1-hour misfire grace. Per-tenant failure isolation. No external cron needed. |
| ✅ | Debt summary in weekly report | WeeklyMetrics now includes total_outstanding, active_debts_count, settled_this_week. Queries CreditSale model. Report shows "Debt book" section: outstanding amount + debtor count + settled this week. Shows "All debts cleared!" when zero. |
| ✅ | Trending products in report | Top 5 most-ordered products by total quantity. Queries OrderItem joined to Order for the week. Shows "Trending products" section: product name + unit count. Skipped when no items. |

## Not Done (MVP)

| # | Task | Description | Priority |
|---|------|-------------|----------|
| ⬜ | Report history on dashboard | Frontend page showing past weekly reports: date, status (sent/failed/skipped), preview text. Query the `weekly_reports` table. | Medium |
| ⬜ | Revenue trend endpoint | `GET /dashboard/revenue-trend?period=weekly` returning time-series data (last 8 weeks) for chart display on dashboard. | Medium |

## Nice to Have (Post-MVP)

| # | Task | Description |
|---|------|-------------|
| ⬜ | Daily flash report | Short daily summary: orders today, revenue today, pending actions. Sent at 8pm. |
| ⬜ | Monthly business review | Comprehensive monthly report: revenue trend, customer growth, top products, category breakdown, credit vs cash ratio. |
| ⬜ | Customer acquisition metrics | Track: new customers per week, repeat order rate, average order value. Add to weekly report. |
| ⬜ | Product performance analytics | Which products sell most, which have highest negotiation rate, which get cancelled most. Dashboard endpoint + charts. |
| ⬜ | Order status funnel | Visual funnel: inquiry → confirmed → paid → delivered. Show conversion rates at each step. |
| ⬜ | Custom report schedule | Trader picks day/time for their report (not just Monday 8am). Already partially supported by TenantReportConfig timezone field. |
| ⬜ | PDF export | Download weekly report as PDF from dashboard. |
| ⬜ | Comparison reports | Compare this week vs last week, this month vs last month side-by-side. |
| ⬜ | Superadmin platform report | Cross-tenant metrics for the platform owner: total traders, total orders, total GMV, growth rate. |
| ⬜ | Report notification preferences | Trader chooses: WhatsApp only, email + WhatsApp, or dashboard only. |

## Key Files

### Backend
| File | Purpose |
|------|---------|
| `app/modules/reports/models.py` | TenantReportConfig + WeeklyReport models |
| `app/modules/reports/service.py` | WeeklyReportService: metrics gathering, formatting, sending |
| `app/modules/reports/router.py` | REST API: config CRUD, preview, trigger |
| `app/modules/reports/schemas.py` | ReportConfigOut, ReportConfigUpdate, responses |
| `alembic/versions/005_add_report_tables.py` | Migration for report tables |
| `app/infra/scheduler.py` | Where the Monday 8am job should be added |

### Frontend
| File | Purpose |
|------|---------|
| `app/(app)/settings/page.tsx` | Settings page containing report config |
| `components/reports/WeeklyReportCard.tsx` | Enable/disable toggle, phone input, preview button |
| `hooks/useReports.ts` | React Query hooks for report config + preview |
| `lib/api/endpoints/reports.ts` | API client for report endpoints |

## Architecture Notes

### Report generation flow
```
Monday 8:00 AM Africa/Lagos (scheduler job — not yet built)
    ↓
For each tenant with reports enabled + recipient set:
    ↓
_gather_metrics(tenant_id, week_start, week_end)
    → queries: conversations, orders, payments, customers
    → computes: WoW deltas
    ↓
render_report(metrics)
    → formats WhatsApp-native text with sections
    ↓
NotificationService.send_message(recipient_phone, report_text)
    → delivers via WhatsApp channel
    ↓
WeeklyReport row logged (sent/failed/skipped + report_text)
```

### Report format example
```
📊 *Weekly Report* — Apr 28 – May 4, 2026

*This week at a glance:*
  💬 12 new leads (+20% vs last week)
  📦 8 orders
  💰 N485,000 revenue (+15%)

🏆 *Top customers:*
  1. Iya Bimpe — 3 orders (N150,000)
  2. Mama Tayo — 2 orders (N85,000)
  3. Bro Femi — 2 orders (N63,000)

⚠️ *Needs your attention:*
  • Customer +2348... waiting 36h for reply
  • Customer +2349... waiting 28h for reply

_Sent by ChatToSales_
```

### Design rules
- Report is warm and actionable, not just numbers
- WoW deltas give context ("is my business growing?")
- "Needs attention" creates urgency without being aggressive
- Timezone-aware: week boundaries use trader's timezone (default Africa/Lagos)
- Idempotent: same week is never sent twice
- Preview lets trader test before enabling
