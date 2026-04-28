"""
app/modules/onboarding/service.py

OnboardingService — state machine for WhatsApp trader onboarding.

Flow overview
-------------
  1. First message → AWAITING_NAME (warm Nigerian-English welcome)
  2. Name captured (2–60 chars) → AWAITING_CATEGORY (category menu)
     2a. Category "other" → ask description → AWAITING_CATALOGUE
  3. Category selected → warm confirmation + AWAITING_CATALOGUE (path menu)
  4a. Path A (option 1, photo) → AWAITING_PHOTO → receive image → OCR → Claude
      extract → AWAITING_PHOTO_CONFIRMATION → YES → complete
  4b. Path B (option 2, voice) → AWAITING_VOICE → receive audio → Whisper →
      Claude extract → AWAITING_VOICE_CONFIRMATION → YES → complete
  4c. Path C (option 3, Q&A) → QA_IN_PROGRESS; up to 30 questions with skip
  4d. Path D (option 4, skip) → complete immediately
  5. Complete → write Trader row → clear Redis → send store link + command guide

State lives in Redis (onboarding:state:{phone_number}), TTL 7 days.
DB write happens only on completion — no partial Trader rows.
"""

import json
import re
import time
from typing import Any

from app.core.logging import get_logger
from app.infra.database import async_session_factory
from app.modules.notifications.service import NotificationService
from app.modules.onboarding import catalogue_templates
from app.modules.onboarding.repository import TraderRepository
from app.modules.onboarding.session import (
    OnboardingState,
    OnboardingStep,
    clear_state,
    get_state,
    set_state,
)

logger = get_logger(__name__)

# ── How long a gap before we say "welcome back" (seconds) ─────────────────────
_WELCOME_BACK_GAP = 6 * 3600  # 6 hours

# ── Q&A checkpoint interval (send a progress note every N items) ───────────────
_QA_CHECKPOINT_EVERY = 5


# ── Copy blocks (Nigerian English / Pidgin) ────────────────────────────────────

_WELCOME = (
    "E kaabo! Welcome to ChatToSales! 🎉\n\n"
    "I go help you sell better, track your customers, know who owes you money, "
    "and understand your business — all from WhatsApp. No app to download!\n\n"
    "To start, wetin be your business name?\n"
    "(e.g. *Mama Caro Provisions* or *Iya Taiwo Fabrics*)"
)

_WELCOME_BACK = (
    "Welcome back! You were setting up your store — make we continue from where we stop! 👋"
)

_NAME_TOO_SHORT = (
    "Hmm, that name dey too short o! Abeg type your full business name "
    "(at least 2 letters)."
)

_CATEGORY_MENU = (
    "*{name}* — I like am! 🔥\n\n"
    "Wetin you mainly sell? Reply with a number:\n\n"
    "1 - Provisions and groceries\n"
    "2 - Fabric and clothing\n"
    "3 - Food and cooked meals\n"
    "4 - Electronics and phones\n"
    "5 - Cosmetics and beauty\n"
    "6 - Building materials\n"
    "7 - Something else (tell me)"
)

_CATEGORY_OTHER_PROMPT = (
    "Got it! Abeg tell me brief brief wetin you sell."
)

_CATALOGUE_MENU = (
    "{category_confirmation}\n\n"
    "Now — you get price list wey I fit read?\n\n"
    "1 - Send me photo of your price list\n"
    "   (handwritten or printed, I fit read am)\n"
    "2 - Send me voice note with your prices\n"
    "3 - Answer small small questions with me\n"
    "4 - Skip for now — I go learn as orders come in"
)

_AWAIT_PHOTO = (
    "Oya! Send me the photo of your price list now.\n\n"
    "Any quality fine — handwritten, printed, whiteboard — as long as the "
    "writing dey legible. If the photo blur I go tell you."
)

_AWAIT_VOICE = (
    "Oya! Record voice note and list your products with their prices.\n\n"
    "Just talk like you dey tell your assistant — e.g. 'Indomie carton na eight "
    "thousand five hundred, rice fifty kg na sixty-three thousand...'"
)

_PROCESSING_PHOTO = (
    "Reading your price list now...\n(give me small time ⏳)"
)

_PROCESSING_VOICE = (
    "I don receive your voice note, transcribing now...\n(give me small time ⏳)"
)

_MEDIA_EXTRACTED = (
    "I found these items — check them:\n\n"
    "{numbered_list}\n\n"
    "Reply *YES* to add all, or tell me wetin to fix\n"
    "(e.g. 'number 2 na Rice 50kg = 63000')"
)

_MEDIA_NOTHING_FOUND = (
    "Hmm, I no fit read this {media_label} well enough.\n\n"
    "No wahala! Choose another way:\n\n"
    "3 - Answer small small questions with me\n"
    "4 - Skip for now, I go learn as orders come in"
)

_MEDIA_CONFIRMED = (
    "Done! All {count} items added to your store. ✅"
)

_WRONG_MEDIA_TYPE = (
    "I dey wait for {expected} o — abeg send {expected} or "
    "type *3* to answer questions instead."
)

_QA_QUESTION = (
    "*{item}* — wetin be your price? "
    "(type number e.g. *8500*, or type *skip* to pass)"
)

_QA_CHECKPOINT = (
    "Good progress! {done} of {total} done. Keep going — type *skip* "
    "anytime to jump to the end."
)

_QA_DONE_EARLY = (
    "No problem, we go skip the rest. Your store dey almost ready! 👍"
)

_COMPLETE = (
    "Your ChatToSales store don ready! 🎉\n\n"
    "*{name}* is now live at:\n"
    "https://chattosales.ng/{slug}\n\n"
    "Share this link with your customers so them fit browse and order from you.\n\n"
    "*HOW YOUR CUSTOMERS ORDER:*\n"
    "- Them go message this number directly\n"
    "- Add me to your customer WhatsApp groups — I go collect orders quietly\n"
    "- Them go visit your store link\n\n"
    "*YOUR COMMANDS:*\n"
    "DEBT [name] [amount] — track who owes you\n"
    "PAID [name] [amount] — clear a debt\n"
    "WHO OWES ME — see your full debt book\n"
    "ORDERS — see all pending orders\n"
    "HELP — see all commands\n\n"
    "Welcome to ChatToSales, *{name}*! 🚀"
)

# ── Category option mapping ───────────────────────────────────────────────────

_CATEGORY_OPTIONS: dict[str, str] = {
    "1": "provisions",
    "2": "fabric",
    "3": "food",
    "4": "electronics",
    "5": "cosmetics",
    "6": "building",
    "7": "other",
}


# ── OnboardingService ─────────────────────────────────────────────────────────


class OnboardingService:
    """
    Drives the WhatsApp onboarding state machine for a single phone number.

    Stateless object — all state is loaded from / saved to Redis on every call.
    DB writes happen only at flow completion (creates the Trader row).
    """

    def __init__(self, repo: TraderRepository) -> None:
        self._repo = repo

    async def handle(
        self,
        *,
        phone_number: str,
        message: str,
        tenant_id: str,
        message_id: str,
        media_id: str | None = None,
        media_type: str | None = None,
    ) -> None:
        """Process one inbound message from a trader."""
        trader = await self._repo.get_by_phone(phone_number)
        if trader is not None:
            return  # already fully onboarded — hand off to order handler

        state = await get_state(phone_number)
        msg = message.strip()

        if state is None:
            await self._start(
                phone_number=phone_number,
                tenant_id=tenant_id,
                message_id=message_id,
            )
            return

        # Welcome back — if the trader was silent for more than 6 hours, greet them.
        last_active: float = state.data.get("_last_active", 0.0)
        if last_active and (time.time() - last_active) > _WELCOME_BACK_GAP:
            await self._reply(
                phone_number=phone_number,
                tenant_id=tenant_id,
                message_id=f"{message_id}_wb",
                text=_WELCOME_BACK,
            )

        # Stamp the activity time in the current state before the step handler
        # overwrites it with a new set_state call.
        updated_data = {**state.data, "_last_active": time.time()}
        await set_state(phone_number, state.step, updated_data)
        state = OnboardingState(step=state.step, data=updated_data)

        match state.step:
            case OnboardingStep.AWAITING_NAME:
                await self._handle_name(phone_number, msg, tenant_id, message_id, state)
            case OnboardingStep.AWAITING_CATEGORY:
                await self._handle_category(phone_number, msg, tenant_id, message_id, state)
            case OnboardingStep.AWAITING_CATALOGUE:
                await self._handle_catalogue_choice(phone_number, msg, tenant_id, message_id, state)
            case OnboardingStep.AWAITING_PHOTO:
                await self._handle_photo(phone_number, msg, tenant_id, message_id, state, media_id, media_type)
            case OnboardingStep.AWAITING_PHOTO_CONFIRMATION:
                await self._handle_media_confirmation(phone_number, msg, tenant_id, message_id, state)
            case OnboardingStep.AWAITING_VOICE:
                await self._handle_voice(phone_number, msg, tenant_id, message_id, state, media_id, media_type)
            case OnboardingStep.AWAITING_VOICE_CONFIRMATION:
                await self._handle_media_confirmation(phone_number, msg, tenant_id, message_id, state)
            case OnboardingStep.QA_IN_PROGRESS:
                await self._handle_qa(phone_number, msg, tenant_id, message_id, state)

    # ── Step handlers ─────────────────────────────────────────────────────────

    async def _start(self, *, phone_number: str, tenant_id: str, message_id: str) -> None:
        await set_state(phone_number, OnboardingStep.AWAITING_NAME, {"_last_active": time.time()})
        await self._reply(
            phone_number=phone_number,
            tenant_id=tenant_id,
            message_id=message_id,
            text=_WELCOME,
        )

    async def _handle_name(
        self,
        phone_number: str,
        msg: str,
        tenant_id: str,
        message_id: str,
        state: OnboardingState,
    ) -> None:
        name = msg.strip()

        if len(name) < 2:
            await self._reply(
                phone_number=phone_number,
                tenant_id=tenant_id,
                message_id=message_id,
                text=_NAME_TOO_SHORT,
            )
            return

        # Truncate silently at 60 chars (per spec)
        name = name[:60]

        await set_state(
            phone_number,
            OnboardingStep.AWAITING_CATEGORY,
            {**state.data, "name": name},
        )
        await self._reply(
            phone_number=phone_number,
            tenant_id=tenant_id,
            message_id=message_id,
            text=_CATEGORY_MENU.format(name=name),
        )

    async def _handle_category(
        self,
        phone_number: str,
        msg: str,
        tenant_id: str,
        message_id: str,
        state: OnboardingState,
    ) -> None:
        # Second pass: category is already "other" and we're waiting for a description
        if state.data.get("_awaiting_other_desc"):
            data = {k: v for k, v in state.data.items() if k != "_awaiting_other_desc"}
            data["category_desc"] = msg[:200]
            await set_state(phone_number, OnboardingStep.AWAITING_CATALOGUE, data)
            await self._reply(
                phone_number=phone_number,
                tenant_id=tenant_id,
                message_id=message_id,
                text=_CATALOGUE_MENU.format(
                    category_confirmation="Noted! I done set up your store."
                ),
            )
            return

        category_key = _CATEGORY_OPTIONS.get(msg.strip())
        if category_key is None:
            await self._reply(
                phone_number=phone_number,
                tenant_id=tenant_id,
                message_id=message_id,
                text="Abeg reply with a number from 1 to 7.",
            )
            return

        data = {**state.data, "category": category_key}

        if category_key == "other":
            await set_state(
                phone_number,
                OnboardingStep.AWAITING_CATEGORY,
                {**data, "_awaiting_other_desc": True},
            )
            await self._reply(
                phone_number=phone_number,
                tenant_id=tenant_id,
                message_id=message_id,
                text=_CATEGORY_OTHER_PROMPT,
            )
            return

        # Build the category confirmation line
        short_name = catalogue_templates.CATEGORY_SHORT_NAMES.get(category_key, category_key.title())
        item_count = len(catalogue_templates.get_items(category_key))
        if item_count > 0:
            confirmation = (
                f"{short_name}! Good choice. 👍\n"
                f"I don load {item_count} common items for you as a starting point."
            )
        else:
            confirmation = f"{short_name}! Good choice. 👍"

        await set_state(phone_number, OnboardingStep.AWAITING_CATALOGUE, data)
        await self._reply(
            phone_number=phone_number,
            tenant_id=tenant_id,
            message_id=message_id,
            text=_CATALOGUE_MENU.format(category_confirmation=confirmation),
        )

    async def _handle_catalogue_choice(
        self,
        phone_number: str,
        msg: str,
        tenant_id: str,
        message_id: str,
        state: OnboardingState,
    ) -> None:
        match msg.strip():
            case "1":
                # Path A — send photo prompt, wait for image
                await set_state(phone_number, OnboardingStep.AWAITING_PHOTO, state.data)
                await self._reply(
                    phone_number=phone_number,
                    tenant_id=tenant_id,
                    message_id=message_id,
                    text=_AWAIT_PHOTO,
                )
            case "2":
                # Path B — send voice prompt, wait for audio
                await set_state(phone_number, OnboardingStep.AWAITING_VOICE, state.data)
                await self._reply(
                    phone_number=phone_number,
                    tenant_id=tenant_id,
                    message_id=message_id,
                    text=_AWAIT_VOICE,
                )
            case "3":
                # Path C — Q&A
                await self._start_qa(phone_number, state.data, tenant_id, message_id)
            case "4":
                # Path D — skip, complete immediately
                await self._complete(phone_number, state.data, tenant_id, message_id)
            case _:
                await self._reply(
                    phone_number=phone_number,
                    tenant_id=tenant_id,
                    message_id=message_id,
                    text="Abeg reply with 1, 2, 3, or 4.",
                )

    # ── Path A: Photo / OCR ───────────────────────────────────────────────────

    async def _handle_photo(
        self,
        phone_number: str,
        msg: str,
        tenant_id: str,
        message_id: str,
        state: OnboardingState,
        media_id: str | None,
        media_type: str | None,
    ) -> None:
        if not media_id or msg != "[image]":
            # Trader sent text while we're waiting for a photo
            await self._reply(
                phone_number=phone_number,
                tenant_id=tenant_id,
                message_id=message_id,
                text=_WRONG_MEDIA_TYPE.format(expected="photo"),
            )
            return

        # Acknowledge immediately so the trader knows we're working on it
        await self._reply(
            phone_number=phone_number,
            tenant_id=tenant_id,
            message_id=f"{message_id}_ack",
            text=_PROCESSING_PHOTO,
        )

        products = await self._process_image(media_id, tenant_id, state.data.get("category", ""))

        if not products:
            await set_state(phone_number, OnboardingStep.AWAITING_CATALOGUE, state.data)
            await self._reply(
                phone_number=phone_number,
                tenant_id=tenant_id,
                message_id=message_id,
                text=_MEDIA_NOTHING_FOUND.format(media_label="photo"),
            )
            return

        await self._send_extracted_product_list(
            phone_number=phone_number,
            tenant_id=tenant_id,
            message_id=message_id,
            state=state,
            products=products,
            next_step=OnboardingStep.AWAITING_PHOTO_CONFIRMATION,
        )

    async def _process_image(
        self, media_id: str, tenant_id: str, category: str
    ) -> list[dict[str, Any]]:
        """Download image → OCR → Claude extract. Returns empty list on any failure."""
        try:
            from app.modules.onboarding.media import (
                download_whatsapp_media,
                extract_products_from_text,
                ocr_image_bytes,
            )
            from app.modules.channels.repository import ChannelRepository

            async with async_session_factory.begin() as session:
                channel_repo = ChannelRepository(session)
                image_bytes = await download_whatsapp_media(media_id, tenant_id, channel_repo)

            ocr_text = await ocr_image_bytes(image_bytes)
            if not ocr_text.strip():
                logger.info("OCR returned empty text for media_id=%s", media_id)
                return []

            return await extract_products_from_text(ocr_text, category)
        except Exception as exc:
            logger.error("Image processing failed media_id=%s: %s", media_id, exc)
            return []

    # ── Path B: Voice / Whisper ───────────────────────────────────────────────

    async def _handle_voice(
        self,
        phone_number: str,
        msg: str,
        tenant_id: str,
        message_id: str,
        state: OnboardingState,
        media_id: str | None,
        media_type: str | None,
    ) -> None:
        if not media_id or msg != "[audio]":
            # Trader sent text while we're waiting for a voice note
            await self._reply(
                phone_number=phone_number,
                tenant_id=tenant_id,
                message_id=message_id,
                text=_WRONG_MEDIA_TYPE.format(expected="voice note"),
            )
            return

        await self._reply(
            phone_number=phone_number,
            tenant_id=tenant_id,
            message_id=f"{message_id}_ack",
            text=_PROCESSING_VOICE,
        )

        products = await self._process_audio(
            media_id, tenant_id, media_type or "audio/ogg", state.data.get("category", "")
        )

        if not products:
            await set_state(phone_number, OnboardingStep.AWAITING_CATALOGUE, state.data)
            await self._reply(
                phone_number=phone_number,
                tenant_id=tenant_id,
                message_id=message_id,
                text=_MEDIA_NOTHING_FOUND.format(media_label="voice note"),
            )
            return

        await self._send_extracted_product_list(
            phone_number=phone_number,
            tenant_id=tenant_id,
            message_id=message_id,
            state=state,
            products=products,
            next_step=OnboardingStep.AWAITING_VOICE_CONFIRMATION,
        )

    async def _process_audio(
        self, media_id: str, tenant_id: str, mime_type: str, category: str
    ) -> list[dict[str, Any]]:
        """Download audio → Whisper → Claude extract. Returns empty list on any failure."""
        try:
            from app.modules.onboarding.media import (
                download_whatsapp_media,
                extract_products_from_text,
                transcribe_audio_bytes,
            )
            from app.modules.channels.repository import ChannelRepository

            async with async_session_factory.begin() as session:
                channel_repo = ChannelRepository(session)
                audio_bytes = await download_whatsapp_media(media_id, tenant_id, channel_repo)

            transcript = await transcribe_audio_bytes(audio_bytes, mime_type)
            if not transcript.strip():
                logger.info("Whisper returned empty transcript for media_id=%s", media_id)
                return []

            return await extract_products_from_text(transcript, category)
        except Exception as exc:
            logger.error("Audio processing failed media_id=%s: %s", media_id, exc)
            return []

    async def _send_extracted_product_list(
        self,
        *,
        phone_number: str,
        tenant_id: str,
        message_id: str,
        state: OnboardingState,
        products: list[dict[str, Any]],
        next_step: str,
    ) -> None:
        """Format the extracted product list and ask the trader to confirm."""
        lines = []
        for i, p in enumerate(products, 1):
            price_fmt = f"N{p['price']:,}"
            lines.append(f"{i}. {p['name']} - {price_fmt}")

        numbered_list = "\n".join(lines)
        new_data = {**state.data, "extracted_products": products}
        await set_state(phone_number, next_step, new_data)
        await self._reply(
            phone_number=phone_number,
            tenant_id=tenant_id,
            message_id=message_id,
            text=_MEDIA_EXTRACTED.format(numbered_list=numbered_list),
        )

    # ── Media confirmation (shared by Path A and Path B) ─────────────────────

    async def _handle_media_confirmation(
        self,
        phone_number: str,
        msg: str,
        tenant_id: str,
        message_id: str,
        state: OnboardingState,
    ) -> None:
        msg_lower = msg.strip().lower()
        products: list[dict[str, Any]] = state.data.get("extracted_products", [])

        # Accept any form of "yes"
        if msg_lower in {"yes", "yeah", "y", "yep", "correct", "ok", "okay", "fine"}:
            count = len(products)
            await self._reply(
                phone_number=phone_number,
                tenant_id=tenant_id,
                message_id=f"{message_id}_confirmed",
                text=_MEDIA_CONFIRMED.format(count=count),
            )
            final_data = {**state.data, "media_catalogue": json.dumps(products)}
            await self._complete(phone_number, final_data, tenant_id, message_id)
            return

        # "yes but number 2 na X = Y" — apply a specific correction then save
        if msg_lower.startswith("yes"):
            correction_text = msg[3:].strip(" ,.-")
            products = _apply_correction(products, correction_text)
            count = len(products)
            await self._reply(
                phone_number=phone_number,
                tenant_id=tenant_id,
                message_id=f"{message_id}_fixed",
                text=f"Fixed! All {count} items added to your store. ✅",
            )
            final_data = {**state.data, "media_catalogue": json.dumps(products)}
            await self._complete(phone_number, final_data, tenant_id, message_id)
            return

        # Anything else — ask again
        await self._reply(
            phone_number=phone_number,
            tenant_id=tenant_id,
            message_id=message_id,
            text=(
                "Reply *YES* to add all these items, or tell me wetin to fix\n"
                "(e.g. 'number 2 na Rice 50kg = 63000')"
            ),
        )

    # ── Path C: Q&A ───────────────────────────────────────────────────────────

    async def _start_qa(
        self,
        phone_number: str,
        data: dict[str, Any],
        tenant_id: str,
        message_id: str,
    ) -> None:
        category = data.get("category", "")
        items = catalogue_templates.get_items(category)

        if not items:
            await self._complete(phone_number, data, tenant_id, message_id)
            return

        qa_data = {**data, "qa_index": 0, "qa_prices": {}}
        await set_state(phone_number, OnboardingStep.QA_IN_PROGRESS, qa_data)
        await self._reply(
            phone_number=phone_number,
            tenant_id=tenant_id,
            message_id=message_id,
            text=_QA_QUESTION.format(item=items[0]),
        )

    async def _handle_qa(
        self,
        phone_number: str,
        msg: str,
        tenant_id: str,
        message_id: str,
        state: OnboardingState,
    ) -> None:
        category = state.data.get("category", "")
        items = catalogue_templates.get_items(category)
        qa_index: int = state.data.get("qa_index", 0)
        qa_prices: dict[str, Any] = state.data.get("qa_prices", {})

        # "skip" or "0" — skip the rest and finish early
        if msg.strip().lower() in {"0", "skip", "s", "done", "finish"}:
            final_data = {**state.data, "qa_prices": qa_prices}
            await self._reply(
                phone_number=phone_number,
                tenant_id=tenant_id,
                message_id=message_id,
                text=_QA_DONE_EARLY,
            )
            await self._complete(phone_number, final_data, tenant_id, f"{message_id}_done")
            return

        # Record price for current item if parseable
        current_item = items[qa_index]
        price = _parse_price(msg)
        if price is not None:
            qa_prices[current_item] = price

        next_index = qa_index + 1

        if next_index >= len(items):
            # All items answered — complete
            final_data = {**state.data, "qa_prices": qa_prices}
            await self._complete(phone_number, final_data, tenant_id, message_id)
            return

        updated_data = {**state.data, "qa_index": next_index, "qa_prices": qa_prices}
        await set_state(phone_number, OnboardingStep.QA_IN_PROGRESS, updated_data)

        # Send progress checkpoint every N items
        if next_index % _QA_CHECKPOINT_EVERY == 0:
            checkpoint = _QA_CHECKPOINT.format(done=next_index, total=len(items))
            await self._reply(
                phone_number=phone_number,
                tenant_id=tenant_id,
                message_id=f"{message_id}_cp",
                text=checkpoint,
            )

        await self._reply(
            phone_number=phone_number,
            tenant_id=tenant_id,
            message_id=message_id,
            text=_QA_QUESTION.format(item=items[next_index]),
        )

    # ── Completion ────────────────────────────────────────────────────────────

    async def _complete(
        self,
        phone_number: str,
        data: dict[str, Any],
        tenant_id: str,
        message_id: str,
    ) -> None:
        name: str = data.get("name", "")
        category: str = data.get("category", "")
        category_desc: str = data.get("category_desc", "")
        qa_prices: dict[str, Any] = data.get("qa_prices", {})
        media_catalogue: str | None = data.get("media_catalogue")

        business_category = (
            category_desc if category == "other" and category_desc else category
        )

        # Prefer the richer media-extracted catalogue; fall back to Q&A prices
        if media_catalogue:
            onboarding_catalogue = media_catalogue
        elif qa_prices:
            onboarding_catalogue = json.dumps(qa_prices)
        else:
            onboarding_catalogue = None

        slug = ""
        async with async_session_factory.begin() as session:
            repo = TraderRepository(session)
            existing = await repo.get_by_phone(phone_number)
            if existing is None:
                slug = await _generate_unique_slug(repo, name)
                await repo.create(
                    phone_number=phone_number,
                    business_name=name,
                    business_category=business_category,
                    store_slug=slug,
                    tenant_id=tenant_id,
                    onboarding_catalogue=onboarding_catalogue,
                )
            else:
                slug = existing.store_slug or ""

        await clear_state(phone_number)

        logger.info(
            "Onboarding complete phone=%s slug=%s category=%s",
            phone_number,
            slug,
            business_category,
        )

        await self._reply(
            phone_number=phone_number,
            tenant_id=tenant_id,
            message_id=f"{message_id}_complete",
            text=_COMPLETE.format(name=name, slug=slug),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _reply(
        self,
        *,
        phone_number: str,
        tenant_id: str,
        message_id: str,
        text: str,
    ) -> None:
        """
        Send a WhatsApp reply to the trader.

        Uses an independent DB session. Failures are logged but never bubble up
        so a bad send never corrupts onboarding state.
        """
        try:
            async with async_session_factory.begin() as session:
                svc = NotificationService(session)
                await svc.send_message(
                    tenant_id=tenant_id,
                    event_id=f"onboarding_reply.{message_id}",
                    recipient=phone_number,
                    message_text=text,
                    channel="whatsapp",
                )
        except Exception as exc:
            logger.error(
                "Onboarding reply failed phone=%s message_id=%s: %s",
                phone_number,
                message_id,
                exc,
            )


# ── Slug generator ────────────────────────────────────────────────────────────


async def _generate_unique_slug(repo: TraderRepository, business_name: str) -> str:
    """
    Produce a URL slug from a business name, guaranteed unique in the DB.

    Runs inside the caller's session so the uniqueness check and the
    subsequent INSERT are in the same transaction.
    """
    base = re.sub(r"\s+", "-", business_name.lower())
    base = re.sub(r"[^a-z0-9-]", "", base)
    base = base.strip("-") or "trader"

    slug = base
    counter = 2
    while await repo.slug_exists(slug):
        slug = f"{base}-{counter}"
        counter += 1
    return slug


# ── Price parser ──────────────────────────────────────────────────────────────


def _parse_price(text: str) -> int | None:
    """
    Extract an integer price from a freeform string.

    Handles common Nigerian formats: "8500", "8,500", "N8500", "₦8,500",
    "8.5k" → 8500. Returns None if no number is found.
    """
    cleaned = text.replace(",", "").replace("N", "").replace("₦", "").strip()
    k_match = re.search(r"(\d+(?:\.\d+)?)\s*k\b", cleaned, re.IGNORECASE)
    if k_match:
        return int(float(k_match.group(1)) * 1000)
    match = re.search(r"\d+", cleaned)
    if match:
        return int(match.group())
    return None


# ── Correction parser ─────────────────────────────────────────────────────────


def _apply_correction(
    products: list[dict[str, Any]], correction_text: str
) -> list[dict[str, Any]]:
    """
    Apply a single correction like "number 2 na Rice 50kg = 63000" to the
    extracted product list. Returns the updated list unchanged if parsing fails.

    Supported formats:
      "number 2 na Rice 50kg = 63000"
      "2 Rice 50kg 63000"
      "no 3 na 8500"  (price-only correction)
    """
    products = list(products)  # shallow copy

    # Try to find a 1-based item number
    num_match = re.search(r"\b(?:number|no\.?|#)?\s*(\d+)\b", correction_text, re.IGNORECASE)
    if not num_match:
        return products

    idx = int(num_match.group(1)) - 1
    if idx < 0 or idx >= len(products):
        return products

    # Extract price — prefer the value after "=" or ":" to avoid picking up
    # the item number itself (e.g. "number 2 na X = 63000" → price is 63000)
    eq_match = re.search(r"[=:]\s*([\d,kK₦N.]+)", correction_text)
    price_text = eq_match.group(1) if eq_match else correction_text
    price = _parse_price(price_text)
    if price is not None:
        products[idx] = {**products[idx], "price": price}

    # Try to extract a new product name (text between "na" and the price)
    name_match = re.search(
        r"\bna\s+(.+?)(?:\s*[=:]\s*\d|$)", correction_text, re.IGNORECASE
    )
    if name_match:
        new_name = name_match.group(1).strip()
        # Remove trailing price digits if they slipped in
        new_name = re.sub(r"\s*\d[\d,]*$", "", new_name).strip()
        if new_name:
            products[idx] = {**products[idx], "name": new_name}

    return products
