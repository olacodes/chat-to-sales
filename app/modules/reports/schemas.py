"""
app/modules/reports/schemas.py

Pydantic v2 schemas for the weekly report API.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.reports.models import WeeklyReportStatus


class ReportConfigOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    tenant_id: str
    enabled: bool
    recipient_phone: str | None
    timezone: str
    created_at: datetime
    updated_at: datetime


class ReportConfigUpdate(BaseModel):
    enabled: bool | None = None
    recipient_phone: str | None = None
    timezone: str | None = None


class WeeklyReportOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    tenant_id: str
    week_start: str
    status: WeeklyReportStatus
    recipient_phone: str | None
    report_text: str | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime


class SendPreviewResponse(BaseModel):
    message: str
    preview_text: str


class TriggerWeeklyResponse(BaseModel):
    message: str
    week_start: str
    status: str
