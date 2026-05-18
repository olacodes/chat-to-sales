# Referral & Marketing Agent System

## 1. Trader-to-Trader Referral Program

### Referral Code
- Every trader gets a unique code after onboarding (e.g. `REF-MAMA-CARO` or `REF-XK7M2P`)
- Referral link: `chattosales.com/join?ref=MAMA-CARO`
- REFER command in WhatsApp menu → shows code + pre-written shareable text

### Reward Structure
| Milestone | Referrer gets | New trader gets |
|-----------|--------------|-----------------|
| Completes onboarding | Nothing (too easy to game) | 90-day free trial |
| First paid order received | 1 week free | — |
| Active for 30 days | 1 month free | — |
| Converts to paid | N500 credit or 1 month free | — |

### How Traders Share
- Post-onboarding WhatsApp message with their link
- REFER command → shareable text they forward
- Pre-written: "I'm using ChatToSales to manage my orders and track who owes me on WhatsApp. Set up your store free: chattosales.com/join?ref=MAMA-CARO"

---

## 2. Marketing Agent / Field Marketer System

### Agent Setup
- Each agent gets: unique code (`AGT-TUNDE-001`), signup link, QR code cards
- During onboarding, agent code is captured (via link or manual entry)

### Payment Structure (Recommended: Tiered)
| Milestone | Agent earns |
|-----------|------------|
| Trader completes onboarding | N100 |
| Trader receives first order | N300 |
| Trader active for 30 days (3+ orders) | N500 |
| Trader converts to paid subscription | N1,000 |
| **Total possible per trader** | **N1,900** |

### Alternative: Recurring Commission
- 10% of trader's subscription for 12 months
- N1,500/month × 10% = N150/month per trader
- 50 active traders = N7,500/month passive income

### Fraud Prevention
- Minimum time between onboardings from same agent
- Trader must have unique phone number
- First order must come from a different phone (not self-ordering)
- Agent code tied to verified phone number
- Flag suspicious patterns (bulk signups, no activity after signup)

### Agent Recruitment
- Start with 5-10 agents per market
- Target: POS agents, market association members, apprentices
- Training: 30-minute WhatsApp video call
- Give each agent 5 pre-printed QR code cards

---

## 3. Ambassador Program

### Criteria
- Active for 30+ days
- 10+ orders processed
- Already referred 1+ traders organically

### Benefits
- Free Alatise tier permanently
- "ChatToSales Ambassador" badge on store page
- Priority support + early access to features
- Store featured on ChatToSales homepage

### Responsibilities
- Demo to neighbouring traders
- Share success stories in WhatsApp groups
- Attend association meetings and mention ChatToSales

---

## 4. Market Association Partnership

- Contact chairman/chairwoman
- Offer: free setup for all members + 20% group discount
- Ask for 10 minutes at next meeting to demo
- Chairman gets permanent free account (becomes ambassador)
- One conversation → access to 100-500 traders

---

## 5. Other Marketing Methods

- **QR Code Stickers**: "Order on WhatsApp" stickers for shop counters (~N50 each)
- **WhatsApp Channel**: Daily posts — trader success stories, tips, updates
- **Market Day Activations**: Demo table at busy markets (budget: N20,000 per activation)
- **Trader Success Story Videos**: 60-second testimonials for WhatsApp Status, Instagram, TikTok

---

## 6. Data Model

### Attribution (on every onboarding)
- attribution_type: organic / referral / agent / partnership
- attribution_code: referral or agent code
- attributed_to_phone: referrer or agent phone

### Referrals Table
- referral_code, referrer_phone, referred_phone
- status: signed_up / first_order / active_30d / converted_to_paid
- reward_type, reward_amount, reward_paid_at

### Agents Table
- agent_id, agent_name, agent_phone, agent_code
- traders_onboarded, traders_active, traders_converted
- total_earned, total_paid, last_payout_at

### Reports Needed
- Agent leaderboard (most active traders this month)
- Referral leaderboard (top referring traders)
- Attribution breakdown (% organic vs referral vs agent)
- Cohort retention (agent-signed vs organic retention)
- ROI per agent (paid to agent vs revenue from their traders)

---

## 7. Payment to Agents

### Phase 1 (Manual)
- Weekly WhatsApp report to each agent with earnings
- Pay via bank transfer weekly/monthly
- Spreadsheet tracking

### Phase 2 (Automated)
- Agent dashboard with real-time stats
- Paystack transfer API for automatic payouts
- Minimum payout threshold: N2,000

---

## Build Priority

| # | Task | Priority | Effort |
|---|------|----------|--------|
| 1 | Referral code generation per trader | High | Small |
| 2 | REFER WhatsApp command + shareable text | High | Small |
| 3 | Attribution tracking on onboarding | High | Medium |
| 4 | Agent code system | High | Medium |
| 5 | Referral status tracking (signup → first order → active → converted) | High | Medium |
| 6 | Agent earnings calculation | Medium | Medium |
| 7 | Agent WhatsApp report (weekly) | Medium | Small |
| 8 | Referral reward auto-apply (free months) | Medium | Small |
| 9 | Superadmin: agent leaderboard + attribution breakdown | Medium | Medium |
| 10 | Ambassador badge on store page | Low | Small |
| 11 | Agent dashboard page | Low | Medium |
| 12 | Automated agent payouts (Paystack transfers) | Low | Medium |
