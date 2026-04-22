"""
app/modules/reports/models.py

TenantReportConfig — per-tenant weekly report settings (enabled, recipient, timezone).
WeeklyReport       — audit log of every send attempt (one row per tenant per week).
"""

from enum import StrEnum

from sqlalchemy import Boolean, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import TenantModel


class WeeklyReportStatus(StrEnum):
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"  # disabled or missing recipient


class TenantReportConfig(TenantModel):
    """
    Stores the report preferences for a tenant.
    One row per tenant — enforced by the unique constraint on tenant_id.
    """

    __tablename__ = "tenant_report_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_report_config_tenant"),
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether the weekly WhatsApp report is enabled for this tenant",
    )
    recipient_phone: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        comment="E.164 phone number to send the report to (business owner)",
    )
    timezone: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="Africa/Lagos",
        server_default="Africa/Lagos",
        comment="IANA timezone used to anchor Mon–Sun week boundaries",
    )


class WeeklyReport(TenantModel):
    """
    One row per weekly report delivery attempt for a tenant.
    The unique index on (tenant_id, week_start) ensures idempotency —
    calling trigger-weekly twice in the same week does nothing the second time.
    """

    __tablename__ = "weekly_reports"
    __table_args__ = (
        Index("ix_weekly_reports_tenant_week", "tenant_id", "week_start", unique=True),
    )

    # ISO date string "YYYY-MM-DD" of the Monday that starts the report week
    week_start: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="ISO date of the Monday starting this report week e.g. '2026-04-20'",
    )
    status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=WeeklyReportStatus.SENT,
        comment="sent | failed | skipped",
    )
    recipient_phone: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        comment="E.164 phone number the report was sent to",
    )
    report_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="The rendered WhatsApp message that was (or would have been) sent",
    )
    error_detail: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Error message when status=failed",
    )
