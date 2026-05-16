# ChatToSales — Complete Feature List

## WhatsApp Commerce
1. Smart Trader Onboarding (4 catalogue paths: OCR, voice, Q&A, passive)
2. Intelligent Order Management (2-layer NLP: rule-based + Claude Haiku)
3. Voice Note Order Processing (Whisper transcription, Nigerian English)
4. Price List OCR (Google Vision API)
5. Product Photo Learning (perceptual hash matching)
6. Order State Machine (INQUIRY → CONFIRMED → PAID / FAILED)
7. Cart-Based Ordering (ORDER:{slug} from store link)

## Payment & Credit
8. Paystack Payment Integration (auto payment links)
9. Payment Webhook Processing (idempotent state transitions)
10. Credit Sales / Debt Tracker
11. Automated Debt Reminders (scheduler, warm tone)
12. Credit Partial Payment Tracking
13. Who Owes Me (debt book summary)

## Trader WhatsApp Commands
14. CONFIRM / CANCEL / PAID (order management)
15. CREDIT (mark order as pay-later)
16. ADD / REMOVE / PRICE (catalogue management)
17. CATALOGUE (view products)
18. CATEGORY (change business category)
19. PRICELIST (upload price list via photo/voice)
20. BANK (set/update bank details with Paystack verification)
21. MENU (interactive two-level menu)
22. ORDERS (view active orders)
23. WHO OWES ME / DEBT (debt tracking)
24. BROADCAST (segmented customer broadcasts)
25. WHO IS (customer purchase history lookup)

## Customer Intelligence
26. Auto-Populated Customer List (from paid orders)
27. Customer Segmentation — Behaviour (new_lead, paid_once, repeat_buyer, vip, lapsed, abandoned_cart)
28. Customer Segmentation — Interest (diverse_buyer, price_sensitive, premium)
29. Customer Segmentation — Timing (weekly, monthly, payday, weekend)
30. Nightly Segment Recompute (APScheduler, 3am WAT)
31. WHO IS Command (instant customer summary with orders, spend, segments, debt)

## Broadcast System
32. BROADCAST WhatsApp Command (segment picker → compose → preview → send)
33. Claude Haiku Message Rewrite (warm Nigerian English)
34. Pre-Send Quality Check (ALL CAPS, spam, link shorteners)
35. Paced Sending (~2/sec, background task)
36. 7-Day Per-Customer Marketing Cap
37. 48-Hour Per-Segment Cooldown
38. 100+ Wide Audience Warning
39. STOP Opt-Out Processing
40. Broadcast Progress Updates + Completion Summary

## Smart Follow-Up
41. Interest Event Tracking (price inquiry, image inquiry, order cancelled)
42. 24-Hour Auto Follow-Up (configurable via FOLLOWUP_DELAY_HOURS)
43. Follow-Up Conversion Tracking
44. Trader Notification on Follow-Up Sent
45. Business Hours Gate (8am–8pm WAT)
46. One Follow-Up Per Product Per Customer

## Negotiation
47. Price Negotiation Detection (specific offer + general haggling)
48. Trader Escalation (Accept / Counter / Decline buttons)
49. Counter-Offer Flow
50. Customer Hold While Trader Decides

## Status Kit (Visual Marketing)
51. 5 HTML Templates (Maison, Editorial, Showcase, Premium, Billboard)
52. 5 Color Schemes (Noir, Gold, Emerald, Midnight, Rose)
53. Playwright HTML→JPEG Rendering
54. Video Generation (CSS animations + FFmpeg + ambient audio)
55. AI Background Removal (rembg)
56. Photo-Adaptive CSS (light vs dark product photos)
57. Daily Auto-Generation (scheduler, deterministic rotation)
58. Web Share Page (one-tap WhatsApp Status sharing)

## Store & Public Pages
59. Customer Store Link (chattosales.com/stores/{slug})
60. Public Store Directory (by category)
61. Store Catalogue Page (mobile-optimized)
62. Order via WhatsApp Button
63. Product Image Upload + R2 Storage

## Dashboard Pages
64. Dashboard Overview (metrics, activity feed, revenue trend)
65. Orders Page (filter by state, search, confirm/pay/cancel actions)
66. Conversations Page (real-time messages, assignment)
67. Payments Page (payment history + status)
68. Customers Page (search, segment filter, order history)
69. Broadcasts Page (history, stats, status filter)
70. Credit Page (debt management)
71. Catalogue Page (product management)
72. Reports Page (weekly report config + history)
73. Settings Page
74. Analytics Page (superadmin only)

## Dashboard API
75. GET /dashboard/metrics (KPIs)
76. GET /dashboard/overview (metrics + recent orders/conversations/payments)
77. GET /dashboard/revenue-trend (weekly chart data)
78. GET /dashboard/today-focus (actionable priorities)
79. GET /marketing/customers (paginated, search, segment filter)
80. GET /marketing/customers/{phone} (detail with recent orders)
81. GET /marketing/segments (segment counts)
82. GET /marketing/broadcasts (history with stats)
83. GET /marketing/broadcasts/{id} (detail with recipients)

## Authentication
84. Phone/OTP Login (WhatsApp-delivered 6-digit code)
85. Email/Password Login
86. Google OAuth Login
87. JWT Token Authentication
88. Superadmin Role (cross-tenant access)
89. Auto-Seed Superadmin from Env Vars

## Multi-Tenancy
90. Tenant-Scoped Data Isolation
91. Tenant Migration on First Dashboard Login
92. Platform Tenant → Dedicated Tenant Transition
93. Redis Cache Busting After Migration

## Real-Time
94. WebSocket Conversations (live message streaming)
95. Redis Event Bus (pub/sub)
96. Conversation Staff Assignment

## Scheduler Jobs
97. Scheduled Message Firing (every 60s)
98. Stale Order Reminders (every 30min, business hours)
99. Debt Reminders (every 6h)
100. Status Kit Generation (daily 6:30am WAT)
101. Weekly Reports (Monday 8am WAT)
102. Smart Follow-Up (hourly, business hours)
103. Segment Recompute (daily 3am WAT)

## Production Infrastructure
104. CI/CD (GitHub Actions, 391 tests on every push)
105. Rate Limiting (Redis sliding window, per-IP)
106. Structured JSON Logging (production) + Request ID Tracing
107. Health Check with DB + Redis Connectivity
108. CORS Enforcement (wildcard blocked in production)
109. Docker Multi-Stage Build
110. Cloudflare R2 Image Storage
111. Alembic Database Migrations (32 migrations)
