"""
Integration tests for dashboard API endpoints.

Tests the actual HTTP endpoints with a real (SQLite) database.
"""

import pytest
from httpx import AsyncClient


class TestDashboardMetrics:
    @pytest.mark.asyncio
    async def test_metrics_returns_200(self, client: AsyncClient):
        resp = await client.get("/api/v1/dashboard/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_orders" in data
        assert "total_revenue" in data
        assert "active_conversations" in data

    @pytest.mark.asyncio
    async def test_metrics_with_orders(self, client: AsyncClient, seed_orders):
        resp = await client.get("/api/v1/dashboard/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_orders"] == 5

    @pytest.mark.asyncio
    async def test_metrics_includes_debt_fields(self, client: AsyncClient):
        resp = await client.get("/api/v1/dashboard/metrics")
        data = resp.json()
        assert "total_outstanding" in data
        assert "active_debts_count" in data
        assert "overdue_debts_count" in data


class TestRevenueTrend:
    """Revenue trend uses date_trunc (PostgreSQL-only), so these tests
    are skipped on SQLite. The endpoint logic is covered by manual E2E tests."""

    @pytest.mark.skip(reason="date_trunc is PostgreSQL-only, not available in SQLite")
    @pytest.mark.asyncio
    async def test_revenue_trend_endpoint_exists(self, client: AsyncClient):
        resp = await client.get("/api/v1/dashboard/revenue-trend")
        assert resp.status_code == 200


class TestReportHistory:
    @pytest.mark.asyncio
    async def test_report_history_returns_200(self, client: AsyncClient):
        resp = await client.get("/api/v1/reports/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_report_history_empty(self, client: AsyncClient):
        resp = await client.get("/api/v1/reports/history")
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_report_history_with_data(self, client: AsyncClient, db_session):
        """Seed a report and verify it appears."""
        from app.modules.reports.models import WeeklyReport, WeeklyReportStatus
        report = WeeklyReport(
            tenant_id="test-tenant",
            week_start="2026-05-05",
            status=WeeklyReportStatus.SENT,
            recipient_phone="+2348141605756",
            report_text="Test report content",
        )
        db_session.add(report)
        await db_session.commit()

        resp = await client.get("/api/v1/reports/history")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["week_start"] == "2026-05-05"
        assert data["items"][0]["status"] == "sent"
        assert data["items"][0]["report_text"] == "Test report content"


class TestReportConfig:
    @pytest.mark.asyncio
    async def test_get_config_returns_200(self, client: AsyncClient):
        resp = await client.get("/api/v1/reports/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "timezone" in data

    @pytest.mark.asyncio
    async def test_update_config(self, client: AsyncClient):
        resp = await client.put(
            "/api/v1/reports/config",
            json={"enabled": True, "recipient_phone": "+2348141605756"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["recipient_phone"] == "+2348141605756"
