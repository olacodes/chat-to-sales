"""
app/modules/marketing/broadcast.py

Broadcast service — composes, quality-checks, and paced-sends broadcasts.
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.infra.database import async_session_factory
from app.modules.marketing.models import (
    Broadcast, BroadcastRecipient, BroadcastStatus, RecipientStatus,
    CustomerListEntry,
)

logger = get_logger(__name__)

# ── Quality checks ───────────────────────────────────────────────────────────

_SPAM_PATTERNS = [
    re.compile(r"[A-Z\s]{20,}"),           # 20+ consecutive uppercase chars
    re.compile(r"!{2,}"),                   # 2+ exclamation marks
    re.compile(r"bit\.ly|tinyurl|shorturl", re.IGNORECASE),  # link shorteners
    re.compile(r"guaranteed|best price ever|limited offer|act now|don't miss", re.IGNORECASE),
]

_QUALITY_ISSUES = {
    "all_caps": "Your message has too much ALL CAPS. WhatsApp may flag this as spam.",
    "exclamation": "Too many exclamation marks. Keep it to one or none.",
    "shortener": "Link shorteners (bit.ly etc.) are flagged by WhatsApp. Use your full store link.",
    "spammy": "This message sounds like spam. Try a more natural, personal tone.",
    "too_short": "Message is too short. Add a personal touch — customers respond better to warm messages.",
}


def check_message_quality(text: str) -> list[str]:
    """Return a list of quality issue descriptions. Empty = message is clean."""
    issues = []
    if len(text.strip()) < 20:
        issues.append(_QUALITY_ISSUES["too_short"])
    if _SPAM_PATTERNS[0].search(text):
        issues.append(_QUALITY_ISSUES["all_caps"])
    if _SPAM_PATTERNS[1].search(text):
        issues.append(_QUALITY_ISSUES["exclamation"])
    if _SPAM_PATTERNS[2].search(text):
        issues.append(_QUALITY_ISSUES["shortener"])
    if _SPAM_PATTERNS[3].search(text):
        issues.append(_QUALITY_ISSUES["spammy"])
    return issues


# ── Claude rewrite ───────────────────────────────────────────────────────────

async def rewrite_broadcast_message(
    raw_text: str,
    trader_name: str,
    store_url: str,
) -> str:
    """
    Use Claude to rewrite the trader's raw message into warm Nigerian English.
    Adds the store name and link.
    """
    try:
        from app.core.config import get_settings
        import anthropic

        settings = get_settings()
        if not settings.ANTHROPIC_API_KEY:
            return raw_text

        prompt = (
            f"You are a WhatsApp marketing assistant for Nigerian traders.\n\n"
            f"The trader '{trader_name}' wants to send this message to their customers:\n"
            f'"{raw_text}"\n\n'
            f"Rewrite it as a warm, friendly WhatsApp broadcast message in good Nigerian English.\n"
            f"Rules:\n"
            f"- Keep it short (2-4 sentences max)\n"
            f"- Warm and personal, not corporate\n"
            f"- No ALL CAPS, max one exclamation mark\n"
            f"- End with the store name and link\n"
            f"- Store name: {trader_name}\n"
            f"- Store link: {store_url}\n\n"
            f"Return ONLY the rewritten message, nothing else."
        )

        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        rewritten = resp.content[0].text.strip().strip('"')
        return rewritten

    except Exception as exc:
        logger.warning("Claude rewrite failed, using original: %s", exc)
        # Fallback: add store name + link to original
        return f"{raw_text}\n\n— {trader_name}\n{store_url}"


# ── Paced sender ─────────────────────────────────────────────────────────────

async def send_broadcast_paced(
    *,
    broadcast_id: str,
    trader_phone: str,
    tenant_id: str,
    platform_tenant_id: str,
    on_progress: callable = None,
) -> None:
    """
    Background task: send broadcast messages one by one with pacing.

    Sends individual private messages (not group). Paced at ~2 per second
    to avoid WhatsApp rate limits. Updates broadcast + recipient status.
    """
    from app.modules.notifications.service import NotificationService

    async with async_session_factory() as session:
        broadcast = (await session.execute(
            select(Broadcast).where(Broadcast.id == broadcast_id)
        )).scalar_one_or_none()

        if not broadcast:
            logger.warning("Broadcast not found: %s", broadcast_id)
            return

        recipients = (await session.execute(
            select(BroadcastRecipient).where(
                BroadcastRecipient.broadcast_id == broadcast_id,
                BroadcastRecipient.status == RecipientStatus.PENDING,
            )
        )).scalars().all()

    # Update broadcast status to SENDING
    async with async_session_factory.begin() as session:
        await session.execute(
            update(Broadcast)
            .where(Broadcast.id == broadcast_id)
            .values(status=BroadcastStatus.SENDING)
        )

    sent_count = 0
    total = len(recipients)
    now = datetime.now(tz=timezone.utc)

    for recipient in recipients:
        # Check 7-day cap
        async with async_session_factory() as session:
            entry = (await session.execute(
                select(CustomerListEntry).where(
                    CustomerListEntry.trader_phone == trader_phone,
                    CustomerListEntry.customer_phone == recipient.customer_phone,
                )
            )).scalar_one_or_none()

        if entry and entry.last_broadcast_at:
            days_since = (now - entry.last_broadcast_at).days
            if days_since < 7:
                # Skip — too recent
                async with async_session_factory.begin() as session:
                    await session.execute(
                        update(BroadcastRecipient)
                        .where(BroadcastRecipient.id == recipient.id)
                        .values(
                            status=RecipientStatus.SKIPPED,
                            skip_reason=f"Last broadcast {days_since}d ago (7-day cap)",
                        )
                    )
                continue

        if entry and entry.opted_out:
            async with async_session_factory.begin() as session:
                await session.execute(
                    update(BroadcastRecipient)
                    .where(BroadcastRecipient.id == recipient.id)
                    .values(status=RecipientStatus.OPTED_OUT, skip_reason="Opted out")
                )
            continue

        # Send the message
        try:
            async with async_session_factory.begin() as session:
                svc = NotificationService(session)
                await svc.send_message(
                    tenant_id=platform_tenant_id,
                    event_id=f"broadcast.{broadcast_id}.{recipient.customer_phone}",
                    recipient=recipient.customer_phone,
                    message_text=broadcast.message_text if hasattr(broadcast, 'message_text') else "",
                    channel="whatsapp",
                )

            send_time = datetime.now(tz=timezone.utc)

            # Update recipient status
            async with async_session_factory.begin() as session:
                await session.execute(
                    update(BroadcastRecipient)
                    .where(BroadcastRecipient.id == recipient.id)
                    .values(status=RecipientStatus.SENT, sent_at=send_time)
                )
                # Update customer last_broadcast_at
                await session.execute(
                    update(CustomerListEntry)
                    .where(
                        CustomerListEntry.trader_phone == trader_phone,
                        CustomerListEntry.customer_phone == recipient.customer_phone,
                    )
                    .values(last_broadcast_at=send_time)
                )

            sent_count += 1

            # Progress callback
            if on_progress and sent_count % 5 == 0:
                await on_progress(sent_count, total)

        except Exception as exc:
            logger.warning(
                "Broadcast send failed: broadcast=%s recipient=%s error=%s",
                broadcast_id, recipient.customer_phone, exc,
            )

        # Pace: ~2 per second (500ms between sends)
        await asyncio.sleep(0.5)

    # Update broadcast as complete
    async with async_session_factory.begin() as session:
        await session.execute(
            update(Broadcast)
            .where(Broadcast.id == broadcast_id)
            .values(
                status=BroadcastStatus.SENT,
                sent_count=sent_count,
                completed_at=datetime.now(tz=timezone.utc),
            )
        )

    logger.info(
        "Broadcast complete: id=%s sent=%d/%d trader=%s",
        broadcast_id, sent_count, total, trader_phone,
    )
