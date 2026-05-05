"""
One-time backfill: create 'started' + 'completed' onboarding events
for all existing traders who completed onboarding before analytics
tracking was added.

Usage:
    cd /Users/sodiqolatunde/work/2026/chatToSales
    source venv/bin/activate
    python scripts/backfill_onboarding_events.py
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def backfill() -> None:
    from app.infra.database import async_session_factory
    from app.modules.onboarding.models import OnboardingStatus, Trader
    from app.modules.onboarding.analytics import (
        OnboardingEvent,
        EVT_STARTED,
        EVT_COMPLETED,
        EVT_PATH_CHOSEN,
    )
    from sqlalchemy import select, func

    async with async_session_factory.begin() as session:
        # Check if events already exist (idempotent)
        existing_count = (
            await session.execute(
                select(func.count()).select_from(OnboardingEvent)
            )
        ).scalar_one()
        if existing_count > 0:
            print(f"Already {existing_count} events in the table. Skipping backfill.")
            return

        # Get all completed traders
        traders = list(
            (
                await session.execute(
                    select(Trader).where(
                        Trader.onboarding_status == OnboardingStatus.COMPLETE
                    )
                )
            ).scalars().all()
        )

        if not traders:
            print("No completed traders found. Nothing to backfill.")
            return

        count = 0
        for trader in traders:
            # Determine path from catalogue data
            if trader.onboarding_catalogue:
                path = "photo"  # Best guess — could be photo or voice
            else:
                path = "skip"

            # Insert 'started' event with trader's created_at timestamp
            started_evt = OnboardingEvent(
                phone_number=trader.phone_number,
                event_type=EVT_STARTED,
                step_name="welcome",
            )
            # Override created_at to match the trader's actual onboarding time
            started_evt.created_at = trader.created_at

            # Insert 'path_chosen' event
            path_evt = OnboardingEvent(
                phone_number=trader.phone_number,
                event_type=EVT_PATH_CHOSEN,
                step_name="catalogue_path",
                path=path,
            )
            path_evt.created_at = trader.created_at

            # Insert 'completed' event
            completed_evt = OnboardingEvent(
                phone_number=trader.phone_number,
                event_type=EVT_COMPLETED,
                step_name="completed",
                path=path,
            )
            completed_evt.created_at = trader.created_at

            session.add(started_evt)
            session.add(path_evt)
            session.add(completed_evt)
            count += 1

        print(f"Backfilled {count} traders ({count * 3} events). Committing...")

    print("Done!")


if __name__ == "__main__":
    asyncio.run(backfill())
