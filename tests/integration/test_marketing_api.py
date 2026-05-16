"""
Integration tests for marketing API endpoints.

Tests /marketing/customers, /marketing/segments, /marketing/broadcasts
with real (SQLite) database via the FastAPI test client.
"""

import pytest
from httpx import AsyncClient


# ── Customers ────────────────────────────────────────────────────────────────


class TestListCustomers:
    @pytest.mark.asyncio
    async def test_returns_200_empty(self, client: AsyncClient):
        resp = await client.get("/api/v1/marketing/customers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_returns_customers(self, client: AsyncClient, seed_customers):
        resp = await client.get("/api/v1/marketing/customers")
        assert resp.status_code == 200
        data = resp.json()
        # 2 active (Mama Tayo opted out but still returned without segment filter)
        assert data["total"] == 3

    @pytest.mark.asyncio
    async def test_search_by_name(self, client: AsyncClient, seed_customers):
        resp = await client.get("/api/v1/marketing/customers?search=Bimpe")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["customer_name"] == "Bimpe Adeyemi"

    @pytest.mark.asyncio
    async def test_search_by_phone(self, client: AsyncClient, seed_customers):
        resp = await client.get("/api/v1/marketing/customers?search=8001111")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_search_no_match(self, client: AsyncClient, seed_customers):
        resp = await client.get("/api/v1/marketing/customers?search=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_filter_by_segment(self, client: AsyncClient, seed_customers):
        resp = await client.get("/api/v1/marketing/customers?segment=vip")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["customer_name"] == "Bimpe Adeyemi"

    @pytest.mark.asyncio
    async def test_filter_by_segment_no_match(self, client: AsyncClient, seed_customers):
        resp = await client.get("/api/v1/marketing/customers?segment=lapsed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_pagination(self, client: AsyncClient, seed_customers):
        resp = await client.get("/api/v1/marketing/customers?limit=1&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["total"] == 3
        assert data["limit"] == 1
        assert data["offset"] == 0

    @pytest.mark.asyncio
    async def test_response_shape(self, client: AsyncClient, seed_customers):
        resp = await client.get("/api/v1/marketing/customers")
        data = resp.json()
        item = data["items"][0]
        assert "id" in item
        assert "customer_phone" in item
        assert "customer_name" in item
        assert "total_orders" in item
        assert "total_spend" in item
        assert "segments" in item
        assert "opted_out" in item


class TestGetCustomer:
    @pytest.mark.asyncio
    async def test_returns_customer(self, client: AsyncClient, seed_customers):
        resp = await client.get("/api/v1/marketing/customers/2348001111111")
        assert resp.status_code == 200
        data = resp.json()
        assert data["customer_name"] == "Bimpe Adeyemi"
        assert data["total_orders"] == 5
        assert "recent_orders" in data

    @pytest.mark.asyncio
    async def test_not_found(self, client: AsyncClient, seed_customers):
        resp = await client.get("/api/v1/marketing/customers/0000000000")
        assert resp.status_code == 404


# ── Segments ─────────────────────────────────────────────────────────────────


class TestSegmentCounts:
    @pytest.mark.asyncio
    async def test_returns_200_empty(self, client: AsyncClient):
        resp = await client.get("/api/v1/marketing/segments")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_customers"] == 0
        assert data["segments"] == []

    @pytest.mark.asyncio
    async def test_returns_segment_counts(self, client: AsyncClient, seed_customers):
        resp = await client.get("/api/v1/marketing/segments")
        assert resp.status_code == 200
        data = resp.json()
        # 2 active customers (Mama Tayo opted out → excluded)
        assert data["total_customers"] == 2
        segment_names = [s["segment"] for s in data["segments"]]
        assert "vip" in segment_names or "repeat_buyer" in segment_names

    @pytest.mark.asyncio
    async def test_segment_has_label(self, client: AsyncClient, seed_customers):
        resp = await client.get("/api/v1/marketing/segments")
        data = resp.json()
        for seg in data["segments"]:
            assert "segment" in seg
            assert "label" in seg
            assert "count" in seg
            assert seg["count"] > 0


# ── Broadcasts ───────────────────────────────────────────────────────────────


class TestListBroadcasts:
    @pytest.mark.asyncio
    async def test_returns_200_empty(self, client: AsyncClient):
        resp = await client.get("/api/v1/marketing/broadcasts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_returns_broadcasts(self, client: AsyncClient, seed_broadcasts):
        resp = await client.get("/api/v1/marketing/broadcasts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    @pytest.mark.asyncio
    async def test_filter_by_status(self, client: AsyncClient, seed_broadcasts):
        resp = await client.get("/api/v1/marketing/broadcasts?status=sent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["status"] == "sent"

    @pytest.mark.asyncio
    async def test_filter_by_status_draft(self, client: AsyncClient, seed_broadcasts):
        resp = await client.get("/api/v1/marketing/broadcasts?status=draft")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["segment"] == "vip"

    @pytest.mark.asyncio
    async def test_broadcast_response_shape(self, client: AsyncClient, seed_broadcasts):
        resp = await client.get("/api/v1/marketing/broadcasts")
        data = resp.json()
        item = data["items"][0]
        assert "id" in item
        assert "segment" in item
        assert "message_text" in item
        assert "total_recipients" in item
        assert "sent_count" in item
        assert "status" in item
        assert "created_at" in item


class TestGetBroadcast:
    @pytest.mark.asyncio
    async def test_returns_broadcast_detail(self, client: AsyncClient, seed_broadcasts):
        # Get the list first to get an ID
        list_resp = await client.get("/api/v1/marketing/broadcasts")
        broadcast_id = list_resp.json()["items"][0]["id"]

        resp = await client.get(f"/api/v1/marketing/broadcasts/{broadcast_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == broadcast_id
        assert "recipients" in data

    @pytest.mark.asyncio
    async def test_not_found(self, client: AsyncClient):
        resp = await client.get("/api/v1/marketing/broadcasts/nonexistent-id")
        assert resp.status_code == 404
