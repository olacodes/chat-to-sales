"""
app/modules/onboarding/session.py

Redis-backed onboarding state for a single WhatsApp phone number.

Each inbound message advances the state machine one step. State is kept in
Redis (not the database) until onboarding completes, so:
- No DB writes happen mid-flow (fast, no partial records).
- Abandoned sessions resume automatically — TTL is 7 days.
- If someone messages again after a week of silence, a fresh flow starts.

Key schema
----------
    onboarding:state:{phone_number}  →  JSON  {step, data}

Step values (see OnboardingStep enum below).
"""

import json
from enum import StrEnum
from typing import Any

from app.infra.cache import get_redis

_KEY_PREFIX = "onboarding:state"
_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


class OnboardingStep(StrEnum):
    AWAITING_NAME = "awaiting_name"
    AWAITING_CATEGORY = "awaiting_category"
    AWAITING_CATALOGUE = "awaiting_catalogue"
    # Waiting for the trader to send an image of their price list
    AWAITING_PHOTO = "awaiting_photo"
    # Waiting for the trader to confirm the OCR-extracted product list
    AWAITING_PHOTO_CONFIRMATION = "awaiting_photo_confirmation"
    # Waiting for the trader to send a voice note listing their prices
    AWAITING_VOICE = "awaiting_voice"
    # Waiting for the trader to confirm the Whisper-transcribed product list
    AWAITING_VOICE_CONFIRMATION = "awaiting_voice_confirmation"
    QA_IN_PROGRESS = "qa_in_progress"


class OnboardingState:
    def __init__(self, step: str, data: dict[str, Any]) -> None:
        self.step = step
        self.data = data


def _key(phone_number: str) -> str:
    return f"{_KEY_PREFIX}:{phone_number}"


async def get_state(phone_number: str) -> OnboardingState | None:
    redis = get_redis()
    raw = await redis.get(_key(phone_number))
    if raw is None:
        return None
    parsed = json.loads(raw)
    return OnboardingState(step=parsed["step"], data=parsed.get("data", {}))


async def set_state(phone_number: str, step: str, data: dict[str, Any]) -> None:
    redis = get_redis()
    payload = json.dumps({"step": step, "data": data})
    await redis.setex(_key(phone_number), _TTL_SECONDS, payload)


async def clear_state(phone_number: str) -> None:
    redis = get_redis()
    await redis.delete(_key(phone_number))
