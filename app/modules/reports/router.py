"""
app/modules/reports/router.py

Weekly report endpoints:
  GET  /reports/config           — get (or auto-create) the tenant's report config
  PUT  /reports/config           — update enabled / recipient_phone / timezone
  POST /reports/send-preview     — generate and send a preview right now
  POST /reports/trigger-weekly   — run the weekly send (cron / external trigger)

The trigger-weekly endpoint is protected by an X-Report-Secret header that must
match settings.REPORT_SECRET. Set a strong random value in production.
"""

from fastapi import APIRouter, Header, HTTPException, status

from app.core.config import get_settings
from app.core.dependencies import DBSessionDep
from app.modules.reports.schemas import (
    ReportConfigOut,
    ReportConfigUpdate,
    SendPreviewResponse,
    TriggerWeeklyResponse,
)
from app.modules.reports.service import WeeklyReportService

router = APIRouter(prefix="/reports", tags=["Reports"])
settings = get_settings()


@router.get("/config", response_model=ReportConfigOut)
async def get_report_config(tenant_id: str, db: DBSessionDep) -> ReportConfigOut:
    """Return the weekly report configuration for the tenant."""
    svc = WeeklyReportService(db)
    config = await svc.get_config(tenant_id)
    return ReportConfigOut.model_validate(config)


@router.put("/config", response_model=ReportConfigOut)
async def update_report_config(
    tenant_id: str,
    body: ReportConfigUpdate,
    db: DBSessionDep,
) -> ReportConfigOut:
    """Update the weekly report settings. Only provided fields are changed."""
    svc = WeeklyReportService(db)
    config = await svc.upsert_config(tenant_id, body)
    return ReportConfigOut.model_validate(config)


@router.post("/send-preview", response_model=SendPreviewResponse)
async def send_preview(tenant_id: str, db: DBSessionDep) -> SendPreviewResponse:
    """
    Generate the previous week's report and send it to the configured recipient now.
    Useful for testing the report before enabling the weekly schedule.
    """
    svc = WeeklyReportService(db)
    try:
        preview_text = await svc.send_preview(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SendPreviewResponse(
        message="Preview sent successfully.",
        preview_text=preview_text,
    )


@router.post("/trigger-weekly", response_model=TriggerWeeklyResponse)
async def trigger_weekly(
    tenant_id: str,
    db: DBSessionDep,
    x_report_secret: str | None = Header(default=None, alias="X-Report-Secret"),
) -> TriggerWeeklyResponse:
    """
    Trigger the weekly report send for the given tenant.

    Protected by the X-Report-Secret header. Call this from a Monday-morning
    cron job or an external scheduler (e.g. GitHub Actions, Railway CRON).

    Idempotent: calling multiple times in the same week is safe.
    """
    if not settings.REPORT_SECRET or x_report_secret != settings.REPORT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Report-Secret header.",
        )
    svc = WeeklyReportService(db)
    report = await svc.run_weekly(tenant_id)
    return TriggerWeeklyResponse(
        message=f"Weekly report {report.status}.",
        week_start=report.week_start,
        status=report.status,
    )
