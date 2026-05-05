"""
app/modules/onboarding/analytics.py

OnboardingEvent — append-only event log for onboarding funnel analytics.

Each significant step in the onboarding flow emits one row.  The admin
dashboard aggregates these into completion rates, drop-off points, and
per-path timing.
"""

from datetime import date, datetime, timezone

from sqlalchemy import Index, String, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import BaseModel
from app.infra.database import async_session_factory


class OnboardingEvent(BaseModel):
    __tablename__ = "onboarding_events"
    __table_args__ = (
        Index("ix_onboarding_events_phone", "phone_number"),
        Index("ix_onboarding_events_type", "event_type"),
        Index("ix_onboarding_events_created", "created_at"),
    )

    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    step_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    path: Mapped[str | None] = mapped_column(String(20), nullable=True)


# ── Event types ──────────────────────────────────────────────────────────────

EVT_STARTED = "started"
EVT_STEP = "step"
EVT_PATH_CHOSEN = "path_chosen"
EVT_COMPLETED = "completed"


# ── Repository ───────────────────────────────────────────────────────────────


class OnboardingAnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def emit(
        self,
        *,
        phone_number: str,
        event_type: str,
        step_name: str | None = None,
        path: str | None = None,
    ) -> None:
        """Append a single onboarding event."""
        self._session.add(OnboardingEvent(
            phone_number=phone_number,
            event_type=event_type,
            step_name=step_name,
            path=path,
        ))

    async def get_analytics(
        self,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> dict:
        """Aggregate onboarding funnel metrics."""
        filters = []
        if from_date:
            filters.append(
                OnboardingEvent.created_at >= datetime(
                    from_date.year, from_date.month, from_date.day,
                    tzinfo=timezone.utc,
                )
            )
        if to_date:
            filters.append(
                OnboardingEvent.created_at < datetime(
                    to_date.year, to_date.month, to_date.day,
                    23, 59, 59, tzinfo=timezone.utc,
                )
            )

        # Total started / completed
        total_started = (await self._session.execute(
            select(func.count(func.distinct(OnboardingEvent.phone_number)))
            .where(OnboardingEvent.event_type == EVT_STARTED, *filters)
        )).scalar_one()

        total_completed = (await self._session.execute(
            select(func.count(func.distinct(OnboardingEvent.phone_number)))
            .where(OnboardingEvent.event_type == EVT_COMPLETED, *filters)
        )).scalar_one()

        completion_rate = (
            round(total_completed / total_started, 2) if total_started > 0 else 0.0
        )

        # Average time to complete (seconds between started and completed per phone)
        # Subquery: earliest started_at per phone
        started_sub = (
            select(
                OnboardingEvent.phone_number,
                func.min(OnboardingEvent.created_at).label("started_at"),
            )
            .where(OnboardingEvent.event_type == EVT_STARTED, *filters)
            .group_by(OnboardingEvent.phone_number)
            .subquery()
        )
        completed_sub = (
            select(
                OnboardingEvent.phone_number,
                func.max(OnboardingEvent.created_at).label("completed_at"),
            )
            .where(OnboardingEvent.event_type == EVT_COMPLETED, *filters)
            .group_by(OnboardingEvent.phone_number)
            .subquery()
        )
        avg_result = (await self._session.execute(
            select(
                func.avg(
                    func.extract("epoch", completed_sub.c.completed_at)
                    - func.extract("epoch", started_sub.c.started_at)
                )
            )
            .select_from(started_sub)
            .join(completed_sub, started_sub.c.phone_number == completed_sub.c.phone_number)
        )).scalar_one()
        avg_completion_minutes = round(avg_result / 60, 1) if avg_result else 0.0

        # By path
        path_rows = (await self._session.execute(
            select(
                OnboardingEvent.path,
                OnboardingEvent.event_type,
                func.count(func.distinct(OnboardingEvent.phone_number)),
            )
            .where(
                OnboardingEvent.event_type.in_([EVT_PATH_CHOSEN, EVT_COMPLETED]),
                OnboardingEvent.path.is_not(None),
                *filters,
            )
            .group_by(OnboardingEvent.path, OnboardingEvent.event_type)
        )).all()

        by_path: dict[str, dict] = {}
        for path_val, evt_type, cnt in path_rows:
            if path_val not in by_path:
                by_path[path_val] = {"chosen": 0, "completed": 0}
            if evt_type == EVT_PATH_CHOSEN:
                by_path[path_val]["chosen"] = cnt
            elif evt_type == EVT_COMPLETED:
                by_path[path_val]["completed"] = cnt

        # Drop-off by step: for phones that started but never completed,
        # find their last step_name
        completed_phones = (
            select(OnboardingEvent.phone_number)
            .where(OnboardingEvent.event_type == EVT_COMPLETED, *filters)
        )
        # Subquery: last step per incomplete phone
        last_step_sub = (
            select(
                OnboardingEvent.phone_number,
                func.max(OnboardingEvent.created_at).label("last_at"),
            )
            .where(
                OnboardingEvent.event_type == EVT_STEP,
                OnboardingEvent.phone_number.not_in(completed_phones),
                *filters,
            )
            .group_by(OnboardingEvent.phone_number)
            .subquery()
        )
        drop_off_rows = (await self._session.execute(
            select(
                OnboardingEvent.step_name,
                func.count(),
            )
            .join(
                last_step_sub,
                (OnboardingEvent.phone_number == last_step_sub.c.phone_number)
                & (OnboardingEvent.created_at == last_step_sub.c.last_at),
            )
            .where(OnboardingEvent.event_type == EVT_STEP)
            .group_by(OnboardingEvent.step_name)
        )).all()

        drop_off_by_step = {step: cnt for step, cnt in drop_off_rows if step}

        return {
            "total_started": total_started,
            "total_completed": total_completed,
            "completion_rate": completion_rate,
            "avg_completion_minutes": avg_completion_minutes,
            "by_path": by_path,
            "drop_off_by_step": drop_off_by_step,
        }


# ── Fire-and-forget helper ───────────────────────────────────────────────────


async def track_onboarding_event(
    *,
    phone_number: str,
    event_type: str,
    step_name: str | None = None,
    path: str | None = None,
) -> None:
    """
    Emit an onboarding event using an independent DB session.

    Fire-and-forget — failures are logged but never bubble up.
    """
    from app.core.logging import get_logger
    logger = get_logger(__name__)
    try:
        async with async_session_factory.begin() as session:
            repo = OnboardingAnalyticsRepository(session)
            await repo.emit(
                phone_number=phone_number,
                event_type=event_type,
                step_name=step_name,
                path=path,
            )
    except Exception as exc:
        logger.warning(
            "Failed to track onboarding event phone=%s type=%s: %s",
            phone_number, event_type, exc,
        )
