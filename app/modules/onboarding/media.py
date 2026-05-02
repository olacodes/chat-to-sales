"""
app/modules/onboarding/media.py

Media processing for onboarding Paths A and B.

Path A (Photo/OCR):
    download_whatsapp_media → ocr_image_bytes → extract_products_from_text

Path B (Voice):
    download_whatsapp_media → transcribe_audio_bytes → extract_products_from_text

All functions are async. Failures raise exceptions that the caller (OnboardingService)
catches and falls back to the Q&A path.
"""

import base64
import json
from typing import Any

import anthropic
import httpx
import openai

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.channels.repository import ChannelRepository
from app.infra.crypto import decrypt_token

logger = get_logger(__name__)
_settings = get_settings()

_META_API_BASE = "https://graph.facebook.com/v25.0"
_VISION_API_BASE = "https://vision.googleapis.com/v1"


# ── Media download ────────────────────────────────────────────────────────────


async def download_whatsapp_media(
    media_id: str,
    tenant_id: str,
    channel_repo: ChannelRepository,
) -> bytes:
    """
    Download raw media bytes from the Meta Cloud API.

    Meta requires two requests:
    1. GET /{media_id} → returns JSON with a short-lived download URL
    2. GET {download_url} → returns the raw bytes
    """
    channel_record = await channel_repo.get_by_tenant_and_channel(
        tenant_id=tenant_id,
        channel="whatsapp",
    )
    if channel_record is None:
        raise ValueError(f"No WhatsApp channel configured for tenant={tenant_id}")

    access_token = decrypt_token(channel_record.encrypted_access_token)
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: resolve the download URL
        meta_resp = await client.get(
            f"{_META_API_BASE}/{media_id}",
            headers=headers,
        )
        meta_resp.raise_for_status()
        download_url: str = meta_resp.json()["url"]

        # Step 2: fetch the actual bytes
        media_resp = await client.get(download_url, headers=headers)
        media_resp.raise_for_status()
        return media_resp.content


# ── OCR (Google Vision) ───────────────────────────────────────────────────────


async def ocr_image_bytes(image_bytes: bytes) -> str:
    """
    Extract text from an image using the Google Vision REST API.

    Returns the full raw text block. Returns an empty string if no text
    is detected or if the API key is not configured.
    """
    if not _settings.GOOGLE_VISION_API_KEY:
        logger.warning("GOOGLE_VISION_API_KEY not set — OCR unavailable")
        return ""

    encoded = base64.b64encode(image_bytes).decode()
    payload = {
        "requests": [
            {
                "image": {"content": encoded},
                "features": [{"type": "TEXT_DETECTION", "maxResults": 1}],
            }
        ]
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{_VISION_API_BASE}/images:annotate",
            params={"key": _settings.GOOGLE_VISION_API_KEY},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    try:
        annotations = data["responses"][0].get("textAnnotations", [])
        if annotations:
            text = annotations[0]["description"]
            logger.info("OCR extracted %d chars", len(text))
            return text
    except (KeyError, IndexError) as exc:
        logger.warning("Vision API response parse error: %s", exc)

    return ""


# ── Transcription (OpenAI Whisper) ────────────────────────────────────────────


async def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    """
    Transcribe audio using OpenAI Whisper, configured for Nigerian/West African English.

    Returns the transcription text. Returns an empty string if the API key is
    not configured or transcription confidence is too low.
    """
    if not _settings.OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set — transcription unavailable")
        return ""

    _ext_map: dict[str, str] = {
        "audio/ogg": "ogg",
        "audio/mpeg": "mp3",
        "audio/mp4": "mp4",
        "audio/aac": "aac",
        "audio/amr": "amr",
        "audio/wav": "wav",
    }
    ext = _ext_map.get(mime_type, "ogg")
    filename = f"audio.{ext}"

    client = openai.AsyncOpenAI(api_key=_settings.OPENAI_API_KEY)
    response = await client.audio.transcriptions.create(
        model="whisper-1",
        file=(filename, audio_bytes, mime_type),
        language="en",
        prompt=(
            "Nigerian market trader listing product names and prices in Nigerian English "
            "or Pidgin English. Products include Indomie, Rice, Peak Milk, Milo, Garri. "
            "Prices are in Naira (₦). Numbers may be spoken in Yoruba (meji=2, meta=3)."
        ),
    )
    text = response.text.strip()
    logger.info("Whisper transcribed %d chars from %s audio", len(text), mime_type)
    return text


# ── Product extraction (Claude) ───────────────────────────────────────────────


async def extract_products_from_text(
    text: str,
    category: str,
) -> list[dict[str, Any]]:
    """
    Use Claude Haiku to extract product names and prices from raw OCR / transcription text.

    Returns a list of dicts: [{"name": "Indomie Carton", "price": 8500}, ...]
    Returns an empty list if extraction fails or the API key is not configured.
    """
    if not _settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — product extraction unavailable")
        return []

    if not text.strip():
        return []

    prompt = (
        f"You are helping a Nigerian informal market trader set up their WhatsApp store.\n"
        f"The trader sells: {category}\n\n"
        "Below is text from their price list (may be handwritten OCR, voice transcription, "
        "or typed in Nigerian Pidgin/English). Extract every product name and price you can find.\n\n"
        "Rules:\n"
        "- Prices are in Nigerian Naira. Accept: 8500, 8,500, N8500, ₦8,500, 8.5k → all mean 8500.\n"
        "- Nigerian brand abbreviations: Ind = Indomie, Pk Milk = Peak Milk, etc.\n"
        "- Yoruba numbers: meji=2, meta=3, merin=4, marun=5, mefa=6, meje=7, mejo=8.\n"
        "- If a product has no clear price, omit it.\n"
        "- Return ONLY a JSON array. No commentary, no markdown fences.\n\n"
        'Format: [{"name": "product name", "price": 8500}, ...]\n\n'
        f"Text:\n{text}\n\n"
        "JSON array:"
    )

    client = anthropic.AsyncAnthropic(api_key=_settings.ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()

    # Strip markdown fences if Claude wrapped the output
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("["):
                raw = part
                break

    try:
        items = json.loads(raw)
        result: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            raw_price = item.get("price")
            if not name or raw_price is None:
                continue
            try:
                price = int(float(str(raw_price).replace(",", "")))
                if price > 0:
                    result.append({"name": name, "price": price})
            except (ValueError, TypeError):
                continue
        logger.info("Claude extracted %d products from %d chars of text", len(result), len(text))
        return result
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Product extraction JSON parse failed: %s | raw=%.200s", exc, raw)
        return []


# ── Product image analysis (Claude Vision) ───────────────────────────────────


async def describe_product_image(
    image_bytes: bytes,
    catalogue: dict[str, int],
    category: str = "",
) -> dict[str, Any]:
    """
    Use Claude Vision to identify a product in a customer photo and attempt
    to match it against the trader's catalogue.

    Returns a dict with:
        description      – human-readable description of the item in the photo
        matched_product  – catalogue item name if a match was found, else None
        matched_price    – price from catalogue if matched, else None
        confidence       – 0.0–1.0 how confident the match is
    """
    if not _settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — image analysis unavailable")
        return {
            "description": "",
            "matched_product": None,
            "matched_price": None,
            "confidence": 0.0,
        }

    encoded = base64.b64encode(image_bytes).decode()

    catalogue_lines = "\n".join(
        f"- {name}: N{price:,}" for name, price in catalogue.items()
    ) if catalogue else "(no catalogue available)"

    prompt = (
        "You are a product identification assistant for a Nigerian market WhatsApp store.\n"
        f"The trader sells: {category or 'general goods'}\n\n"
        "A customer sent this photo asking about a product. Identify what is in the image.\n\n"
        f"The trader's catalogue:\n{catalogue_lines}\n\n"
        "Instructions:\n"
        "- Describe the item in the photo in 1-2 short sentences.\n"
        "- If the item matches a product in the catalogue above, return its exact name.\n"
        "- Be generous with matching — e.g. a photo of any rice bag can match 'Rice 50kg'.\n"
        "- If no catalogue match, return null for matched_product.\n"
        "- Return ONLY valid JSON. No commentary, no markdown fences.\n\n"
        'Format: {"description": "...", "matched_product": "exact catalogue name or null", "confidence": 0.0 to 1.0}\n\n'
        "JSON:"
    )

    client = anthropic.AsyncAnthropic(api_key=_settings.ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": encoded,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )

    raw = response.content[0].text.strip()

    # Strip markdown fences if Claude wrapped the output
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                raw = part
                break

    try:
        data = json.loads(raw)
        description = str(data.get("description", "")).strip()
        matched_product = data.get("matched_product")
        confidence = float(data.get("confidence", 0.0))

        # Validate the matched product actually exists in the catalogue
        matched_price: int | None = None
        if matched_product and isinstance(matched_product, str):
            matched_product = matched_product.strip()
            # Case-insensitive lookup
            for cat_name, cat_price in catalogue.items():
                if cat_name.lower() == matched_product.lower():
                    matched_product = cat_name  # use exact catalogue casing
                    matched_price = cat_price
                    break
            else:
                # Claude returned a name not in catalogue — treat as no match
                matched_product = None
                confidence = min(confidence, 0.3)

        logger.info(
            "Claude Vision: description=%r matched=%s confidence=%.2f",
            description[:80],
            matched_product,
            confidence,
        )
        return {
            "description": description,
            "matched_product": matched_product,
            "matched_price": matched_price,
            "confidence": confidence,
        }
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("Image analysis JSON parse failed: %s | raw=%.200s", exc, raw)
        return {
            "description": "",
            "matched_product": None,
            "matched_price": None,
            "confidence": 0.0,
        }
