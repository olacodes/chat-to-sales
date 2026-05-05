# Feature 3: Self-Building Product Catalogue — Task Tracker

## Done

| # | Task | Description |
|---|------|-------------|
| ✅ | Pre-loaded catalogue templates | 30 starter items per category (7 categories), used in Q&A onboarding path |
| ✅ | Path A: Photo OCR catalogue | Google Vision OCR → Claude Haiku extraction → JSON product list |
| ✅ | Path B: Voice catalogue | OpenAI Whisper → Claude Haiku extraction → JSON product list |
| ✅ | Path C: Q&A catalogue | Sequential price prompts for template items, skip support, checkpoints every 5 |
| ✅ | Path D: Skip (passive) | Empty catalogue, builds from customer orders and image inquiries |
| ✅ | Catalogue JSON storage | Stored in `Trader.onboarding_catalogue` as JSON text (supports both dict and list formats) |
| ✅ | Catalogue parsing at runtime | `_parse_catalogue()` normalizes both dict and list JSON formats to `{name: price}` |
| ✅ | Image resize before Claude Vision | 768x768 max via Pillow (LANCZOS), JPEG quality 85 — ~50% token cost reduction |
| ✅ | Claude Vision catalogue matching | Sends resized image + catalogue to Claude Haiku, identifies product by name, returns confidence |
| ✅ | Claude Vision product-only prompt | Strict rules: ignore background/lighting/surface, canonical form, max 20 words |
| ✅ | Claude Vision conditional call | Only called when catalogue has items — skipped entirely for empty catalogues (zero API cost) |
| ✅ | Perceptual image hashing (pHash) | `imagehash.phash(hash_size=16)` computes 64-char hex hash from image bytes |
| ✅ | pHash Hamming distance comparison | Bit-level comparison between two hashes, threshold ≤12 for match |
| ✅ | ProductDescription model | PostgreSQL table: trader_phone, product_name, price, description, image_hash, confirmed |
| ✅ | ProductDescription repository | save(), list_confirmed_for_trader(), find_best_match() |
| ✅ | pHash-first matching | Hash check runs BEFORE Claude Vision — instant match, zero API cost, ~5ms |
| ✅ | Price resolution order | 1) Catalogue price (latest), 2) Stored price from ProductDescription (fallback) |
| ✅ | Image inquiry forwarding to trader | Photo sent to trader with "Reply with product name and price" prompt |
| ✅ | Pending image inquiry session | Redis `image:inquiry:{trader_phone}` (24h TTL) stores customer_phone, image_hash, tenant/conversation IDs |
| ✅ | Trader reply parsing | Extracts product name (text before price) and price (last number) from free-text reply |
| ✅ | Trader reply learning | Saves ProductDescription with pHash + product + price → future photos auto-match |
| ✅ | Trader confirmation message | "✅ Got it! I don save {product} at N{price}. Next time I go answer automatically." |
| ✅ | Customer quantity picker | WhatsApp list message: Buy 1-5 + Cancel, price × qty per row |
| ✅ | Order after quantity selection | Order created, trader notified with photo (reply-to linked) + Confirm/Decline buttons |
| ✅ | Correct order flow timing | Trader NOT notified until customer selects quantity (fixed race condition bug) |
| ✅ | media_id in order session | Stored in Redis so CONFIRM handler can forward the original photo to trader |
| ✅ | Embedding column removed | Legacy OpenAI text-embedding column dropped from model and DB |
| ✅ | Description made optional | Claude Vision description nullable — not needed when pHash handles matching |
| ✅ | Alembic migrations | 016 (create table), 017 (add embedding), 018 (add price), 019 (add image_hash), 020 (drop embedding, nullable description) |

## Undone

| # | Task | Description | MVP |
|---|------|-------------|-----|
| ⬜ | Dashboard catalogue management | Web UI for traders to add/edit/delete products with names, prices, and photos | ✅ Yes |
| ⬜ | Catalogue sync | Write learned products (from ProductDescription) back to `Trader.onboarding_catalogue` so they appear on the store page | ✅ Yes |
| ⬜ | Product deletion | Let trader remove a learned product via WhatsApp ("DELETE Indomie") or dashboard — currently incorrect associations persist forever | ✅ Yes |
| ⬜ | Multiple pending inquiries per trader | Currently one pending inquiry per trader (Redis key overwrite) — need queue so concurrent customer photos don't overwrite each other | ✅ Yes |
| ⬜ | Product image storage | Store actual product images (Vercel Blob) for display on the public store page — currently store page has no photos | ✅ Yes |
| ⬜ | Product deduplication | Multiple ProductDescription rows can exist for the same product from different photos — merge into single product with multiple hashes | ⬜ No |
| ⬜ | Catalogue export | Download catalogue as CSV/PDF for printing price lists or sharing with suppliers | ⬜ No |
| ⬜ | Price history | Track price changes over time per product — show trends in dashboard | ⬜ No |
| ⬜ | Stock management | Track inventory levels, auto-hide out-of-stock items from store page, low-stock alerts | ⬜ No |
| ⬜ | Product categories within store | Group products by sub-category (e.g., "Beverages", "Grains", "Oils" within Provisions) | ⬜ No |
| ⬜ | Catalogue WhatsApp commands | Trader types "CATALOGUE" to see their full product list, "PRICE Indomie 9500" to update a price | ⬜ No |
| ⬜ | Product search | Customer types "search rice" to find matching products without browsing the full catalogue | ⬜ No |

## Nice to Have

| # | Task | Description | MVP |
|---|------|-------------|-----|
| 💡 | CLIP embeddings upgrade | Replace pHash with CLIP image embeddings for better accuracy on visually similar but different products (e.g., different rice brands in similar bags) | ⬜ No |
| 💡 | Community catalogue | Shared database of ~500 common Nigerian market products with reference images — match before asking trader, works across all stores | ⬜ No |
| 💡 | Product photo from dashboard | Let traders upload higher-quality product photos via web dashboard (not WhatsApp-compressed) for the store page | ⬜ No |
| 💡 | Auto price suggestion | Suggest prices based on similar products from other traders in the same category and location | ⬜ No |
| 💡 | Barcode/QR scanning | Customer scans product barcode via camera → auto-identify product from global database (Open Food Facts, etc.) | ⬜ No |
| 💡 | Bulk photo catalogue | Trader sends 10 photos at once → system processes all, asks for names/prices in batch, adds all to catalogue | ⬜ No |
| 💡 | Smart product naming | When trader replies with just a price (no name), use Claude to generate a product name from the image description instead of "Product" | ⬜ No |
| 💡 | Seasonal catalogue | Auto-suggest seasonal items (e.g., "Ramadan pack", "Christmas provisions", "Back to school") based on calendar | ⬜ No |
| 💡 | Price alert | Notify trader when competitors change prices for similar products in the same market | ⬜ No |
| 💡 | Catalogue health score | Dashboard metric: "Your catalogue is 65% complete — 12 products have no photo, 5 haven't been priced since last month" | ⬜ No |
| 💡 | Product variants | Support variants like "Rice 25kg" and "Rice 50kg" as related products with different prices | ⬜ No |
| 💡 | Catalogue import from competitor | Trader shares a competitor's store link → system imports their product names (not prices) as a starting point | ⬜ No |
