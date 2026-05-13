# Feature 7: Customer Store Link — Task Tracker

## Overview

Lightweight mobile page at `chattosales.com/stores/{slug}` where customers can browse a trader's catalogue and order via WhatsApp. Designed to load in <2 seconds on 2G — deliberately minimal. The store link is the trader's digital storefront they share with customers.

## Done

| # | Task | Description |
|---|------|-------------|
| ✅ | Store API endpoints | `GET /stores` (public listing, all completed stores), `GET /stores/{slug}` (individual store). Unauthenticated. ISR cached (60s detail, 120s listing). |
| ✅ | Store slug generation | Sanitized from business name (lowercase, hyphens, special chars removed). Unique constraint + collision detection with `-2` suffix. |
| ✅ | Smart ordering URL | Phase 1 (platform number): `wa.me/{platform}?text=ORDER:{slug}`. Phase 2 (trader's own WABA): `wa.me/{trader_phone}`. Auto-detects which phase via channel lookup. |
| ✅ | Store directory page | `/stores` — all public stores grouped by business category with emojis. Responsive grid (1/2/3 columns). Empty state with signup CTA. SEO metadata. |
| ✅ | Individual store page | `/stores/{slug}` — dynamic page showing trader name, category, catalogue. Not-found fallback. SEO with dynamic metadata per store. |
| ✅ | Interactive catalogue UI | `StoreCatalogue` component: quantity selectors (+/−), real-time order summary, sticky bottom bar with item count + total. "Order on WhatsApp" button builds structured `ORDER:{slug}\nItem x2\n...` message. |
| ✅ | Empty catalogue fallback | When store has no products: "Send message to order" CTA linking to WhatsApp. |
| ✅ | Store not-found page | Custom 404 with links to signup and store directory. Warm messaging. |
| ✅ | Post-onboarding confirmation | `/onboarding` page: "Your store is live!" with store URL, copy button, WhatsApp share button. |
| ✅ | Catalogue management dashboard | `/catalogue` page: editable product table, inline price editing, add/remove products, photo upload OCR, search/filter, save changes. |
| ✅ | Store API client | `storeApi.get(slug)` — public fetch with no authentication headers. Types: CatalogueItemOut, TraderStoreOut. |
| ✅ | Cart order parsing | Backend `_parse_cart_message()` parses `ORDER:{slug}\nItem x2\nItem2 x1` from the store page's WhatsApp button. Routes to `handle_cart_order()`. |
| ✅ | Customer routing session | When customer sends `ORDER:{slug}`, a routing session is stored in Redis (4h TTL) so follow-up messages (YES/NO) reach the correct trader. |
| ✅ | Web catalogue API | `GET /stores/catalogue` (authenticated, trader's own), `PUT /stores/catalogue` (replace full catalogue + bust cache). |
| ✅ | Pricelist extraction | `POST /stores/setup/extract-pricelist` — upload photo, OCR + Claude extraction, return products for editable table. |

## Not Done (MVP)

| # | Task | Description | Priority |
|---|------|-------------|----------|
| ⬜ | 2G performance optimization | Test and optimize for sub-2-second load on slow networks. Image lazy loading, minimal JS, critical CSS inlining. | High |
| ✅ | Open Graph / social sharing | Dynamic OG metadata per store: title (business name), description (product count + CTA), full openGraph + twitter card tags. Dynamic OG image generated via `next/og` ImageResponse (1200x630): dark green background, store name, category, top 4 product names as pills, WhatsApp green CTA button, ChatToSales branding. Revalidates every 5 min. |
| ⬜ | Store page bank details | Show trader's bank details on the store page (optional, trader-configurable) so customers can pay before messaging. | Medium |
| ⬜ | Product search on store page | Search/filter bar on store pages with large catalogues (>20 products). | Medium |
| ✅ | Structured data (JSON-LD) | LocalBusiness schema with category-mapped additionalType (GroceryStore, ElectronicsStore, ClothingStore, etc.) + OrderAction pointing to WhatsApp. Per-product Product schema (up to 20) with Offer (NGN price, InStock, seller). Injected as script tags in store page. | Medium |
| ✅ | Sitemap for store pages | Dynamic sitemap.xml fetches all active store slugs from `GET /api/v1/stores` (revalidates hourly). Each store page at priority 0.7, changeFrequency daily. Static pages preserved. | Medium |

## Nice to Have (Post-MVP)

| # | Task | Description |
|---|------|-------------|
| ⬜ | Store banner/hero image | Trader uploads a banner photo for their store page. |
| ⬜ | Store description | "About" section where trader describes their business. |
| ⬜ | Business hours | Display open/closed status based on trader-set hours. |
| ⬜ | Product categories on store | Group products by sub-category on large catalogues (e.g. "Phones", "Accessories"). |
| ⬜ | Store analytics | Track: page views, unique visitors, WhatsApp clicks, conversion rate. Show in dashboard. |
| ⬜ | Featured stores | Superadmin can feature/promote stores on the directory page. |
| ⬜ | Customer reviews | Customers rate their experience after order completion. |
| ⬜ | QR code for store link | Generate printable QR code that traders can display in their physical shop. |
| ⬜ | Offline / PWA support | Progressive enhancement: store page works offline after first load. |
| ⬜ | Multi-language store | Store page content in Yoruba, Pidgin, or other languages based on customer preference. |
| ⬜ | Delivery/pickup options | Display delivery areas, shipping cost, or pickup location on store page. |

## Key Files

### Backend
| File | Purpose |
|------|---------|
| `app/modules/onboarding/router.py` | Store API endpoints (public + authenticated) |
| `app/modules/onboarding/models.py` | Trader model with store_slug |
| `app/modules/onboarding/repository.py` | list_completed, get_by_slug, slug_exists |
| `app/modules/onboarding/schemas.py` | TraderStoreOut, StoreListItem, CatalogueItem |
| `app/modules/channels/repository.py` | Phase 1/2 WABA detection |
| `app/modules/orders/handlers.py` | Cart order parsing from ORDER:{slug} messages |

### Frontend
| File | Purpose |
|------|---------|
| `app/(marketing)/stores/page.tsx` | Store directory (public listing) |
| `app/(marketing)/stores/[slug]/page.tsx` | Individual store page |
| `app/(marketing)/stores/[slug]/StoreCatalogue.tsx` | Interactive catalogue + WhatsApp ordering |
| `app/(marketing)/stores/[slug]/not-found.tsx` | Store 404 page |
| `app/(auth)/onboarding/page.tsx` | Post-signup store confirmation |
| `app/(app)/catalogue/page.tsx` | Trader catalogue management dashboard |
| `lib/api/endpoints/store.ts` | Public store API client |

## Architecture Notes

### Two-phase ordering
- **Phase 1**: Customer orders through shared ChatToSales WhatsApp number. `ORDER:{slug}` prefix identifies the trader. Most traders start here.
- **Phase 2**: Trader connects their own WhatsApp Business Account. Customer messages the trader directly. Store page detects this via channel lookup.

### Store URL format
`chattosales.com/stores/{business-name-slugified}`
- Spaces → hyphens, lowercase, special chars removed
- Collision: append `-2`, `-3`, etc.
- Examples: `mama-caro-provisions`, `iya-taiwo-fabrics`

### Design rules
- Page loads in <2 seconds on 2G — deliberately minimal
- No login required to view stores or browse catalogues
- Ordering always routes through WhatsApp (no checkout on the web)
- Store page is supplementary to the WhatsApp experience, not a replacement
