# Feature 9: Product Images & WhatsApp Status Kit — Task Tracker

## Overview

Two-part feature: (1) Product image management — traders add photos to catalogue products via WhatsApp or dashboard, stored in Cloudflare R2. (2) WhatsApp Status Content Kit — daily ready-to-post Status images generated from the trader's catalogue, turning their products into a content engine.

## Done

| # | Task | Description |
|---|------|-------------|
| ✅ | Cloudflare R2 storage utility | `app/infra/storage.py`: upload_product_image (resize to 800px, JPEG, upload to R2, return CDN URL), delete_product_image. S3-compatible boto3 client. |
| ✅ | R2 configuration | R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME, R2_PUBLIC_URL env vars in config.py. |
| ✅ | product_images table | Migration 027: trader_phone, product_name (unique together), image_url, image_hash (pHash). One image per product per trader. |
| ✅ | ProductImage model + repository | ProductImage ORM model. Repository: upsert, get, list_for_trader, delete. Registered in main.py. |
| ✅ | WhatsApp photo upload (with caption) | Trader sends photo with caption matching a product → auto-saved to R2: "Photo saved for Indomie Carton (N8,500)." |
| ✅ | WhatsApp photo upload (no caption) | Trader sends photo without caption → list picker: "Which product is this for?" → trader taps → saved. Image stored temporarily in Redis session (base64) during selection. |
| ✅ | pHash computation on upload | Every uploaded image gets a perceptual hash stored for future image matching. |
| ✅ | Dashboard product image API | `GET /stores/images` (list all images), `POST /stores/images/{product_name}` (upload photo to R2). Authenticated, resize + pHash. |
| ✅ | Dashboard catalogue photo column | Photo column in catalogue table: thumbnail if image exists, camera icon upload button if not. Click to upload, image appears immediately. |
| ✅ | WhatsApp templates | product_photo_saved, product_photo_which_product (list picker). |
| ✅ | Session state | TRADER_AWAITING_PHOTO_PRODUCT for the "which product?" selection flow. |
| ✅ | boto3 dependency | Added to requirements.txt for S3-compatible R2 access. |
| ✅ | Passive collection from image inquiries | Customer sends product photo → image uploaded to R2 immediately with temp name. When trader replies with price → product_images row created automatically with the pre-uploaded URL. Works even when trader replies with price only (saves as "Product"). |
| ✅ | Status Kit photo card generator | Pillow-based: product photo fills 1080x1920 background, dark overlay, white text (trader name, product name, price in WhatsApp green, store link, "Message to order" CTA). Auto word-wrap, center crop, ~40-50KB JPEG. |
| ✅ | Status Kit text card generator | Gradient green background, same text layout. Fallback when no product photo available. |
| ✅ | Daily Status Kit scheduler | Cron job at 5:30 AM UTC (6:30 AM WAT). For each completed trader: picks 2-3 products, generates photo or text cards, uploads to R2, sends via WhatsApp image URL, then sends "Share to your Status!" prompt. Business hours gated. |
| ✅ | Product rotation logic | Deterministic rotation: day_index × 3 mod catalogue_size. Every product gets visibility over time. Different products each day, wraps around. |
| ✅ | Send image by URL | NotificationService.send_image_url() — sends WhatsApp images via public R2 URL instead of media_id. Uses Meta Cloud API {"link": url} format. |
| ✅ | DejaVu fonts in Docker | fonts-dejavu-core added to Dockerfile for consistent text rendering in generated images. |
| ✅ | Store page product images | `GET /stores/{slug}` now enriches catalogue items with `image_url` from product_images table. StoreCatalogue component shows 48x48 rounded thumbnails per product. Falls back to shopping bag emoji when no image. Lazy loaded for performance. |

| ✅ | Photo replacement on dashboard | Click existing thumbnail → hover shows pencil overlay → file picker → replaces image via same upsert mutation. Both upload new + replace existing use unified label with hidden file input. |

## Not Done (MVP)

All MVP tasks complete.

## Nice to Have (Post-MVP)

| # | Task | Description |
|---|------|-------------|
| ⬜ | Status Kit video (Ken Burns) | Take a single product photo → slow zoom/pan over 5-7 seconds → overlay text. FFmpeg. Creates engaging Status video from one photo. |
| ⬜ | Status Kit slideshow video | Combine 3-5 product photos into a 15-second video with transitions. Each slide shows product name + price. Ends with store link. |
| ⬜ | Seasonal templates | Christmas, Ramadan, Black Friday themed Status cards. Trader selects theme in settings. |
| ⬜ | Status Kit performance tracking | "Your Status posts generated 5 orders this week." Track store link clicks from Status-shared posts. |
| ⬜ | Trader brand color | Trader picks a brand color during onboarding or settings. Used in Status cards and store page. |
| ⬜ | AI product image generation | For products without photos: generate realistic product images using AI (Vercel AI Gateway). "Generate a photo of a 50kg bag of rice." |
| ⬜ | Bulk photo upload | Dashboard: drag and drop multiple photos, match each to a product. |
| ⬜ | Photo from URL | Trader pastes a product image URL instead of uploading a file. |
| ⬜ | Image quality optimization | WebP conversion for smaller file sizes. Progressive JPEG for faster loading on 2G. |
| ⬜ | Customer screenshot matching | When a customer screenshots a trader's WhatsApp Status and sends it, the pHash from product_images matches it automatically. Requires stored image hashes. |
| ⬜ | One-time photo collection prompt | After onboarding: "Send me photos of your top 5 products and I'll create daily Status posts for you!" Guided flow to populate product images. |

## Key Files

### Backend
| File | Purpose |
|------|---------|
| `app/infra/storage.py` | Cloudflare R2 client (upload, delete, resize) |
| `app/infra/status_kit.py` | Pillow image generator (photo card + text card, 1080x1920) |
| `app/infra/scheduler.py` | Daily Status Kit cron job (_send_status_kit) |
| `app/modules/orders/product_images.py` | ProductImage model + repository |
| `app/modules/onboarding/router.py` | Image API endpoints (GET /images, POST /images/{name}) |
| `app/modules/orders/service.py` | WhatsApp photo handler, passive collection from inquiries |
| `app/modules/orders/whatsapp.py` | Photo templates (saved, which_product picker) |
| `app/modules/orders/session.py` | TRADER_AWAITING_PHOTO_PRODUCT state |
| `app/modules/notifications/service.py` | send_image_url() for WhatsApp image-by-URL |
| `app/core/config.py` | R2 configuration vars |
| `alembic/versions/027_add_product_images.py` | Migration |
| `Dockerfile` | fonts-dejavu-core for image text rendering |

### Frontend
| File | Purpose |
|------|---------|
| `app/(app)/catalogue/page.tsx` | Photo column in catalogue table |
| `hooks/useCatalogue.ts` | useProductImages, useUploadProductImage hooks |
| `lib/api/endpoints/onboarding.ts` | getProductImages, uploadProductImage API calls |

## Architecture Notes

### Image storage flow
```
Trader uploads photo (WhatsApp or dashboard)
    ↓
Pillow: resize to max 800px, JPEG quality 85
    ↓
Upload to Cloudflare R2: products/{phone}/{slug}.jpg
    ↓
Compute pHash (imagehash library)
    ↓
Upsert product_images row (image_url + image_hash)
    ↓
Image available everywhere:
  - Dashboard catalogue table (thumbnail)
  - Store page (when built)
  - Status Kit (when built)
  - Image matching (pHash)
```

### Storage costs (estimated)
- 100 traders × 30 products × 100KB = ~300MB storage (well within R2 free tier of 10GB)
- Egress: $0 (Cloudflare R2 has zero egress costs)
- At 1,000 traders: ~3GB storage, still within free tier

### Design rules
- One image per product per trader (unique constraint, upsert on re-upload)
- Images resized to max 800px (WhatsApp Status friendly, small file size)
- JPEG format, quality 85 (good balance of quality vs size)
- pHash stored for every image (enables future customer screenshot matching)
- R2 URL stored in PostgreSQL, binary never in the database
- Graceful degradation: no image = text-only card / no thumbnail
