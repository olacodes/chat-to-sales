"""
Service tests for the clarification flow.

Tests numbered list extraction, quick-pick logic, and session context.
Uses fakeredis for session storage.
"""

import json
import re
from typing import Any

import pytest


# ── Numbered list extraction (regex) ─────────────────────────────────────────

def _extract_numbered_items(reply_text: str) -> list[dict[str, Any]]:
    """
    Same regex as service.py — extracted here for testability.
    Matches: "1. Name - N330,000" / "1. Name: ₦330,000" / "1. Name — N330k"
    """
    items: list[dict[str, Any]] = []
    for m in re.finditer(
        r"(\d+)\.\s+(.+?)\s*[-\u2013:]\s*[N\u20a6]?\s*([\d,]+(?:\.\d+)?)",
        reply_text,
    ):
        price_str = m.group(3).replace(",", "").split(".")[0]
        if price_str.isdigit():
            items.append({
                "index": int(m.group(1)),
                "name": m.group(2).strip(),
                "price": int(price_str),
            })
    return items


class TestNumberedListExtraction:
    def test_dash_n_format(self):
        text = "1. UK iPhone 12 64GB - N290,000\n2. UK iPhone 12 128GB - N330,000"
        items = _extract_numbered_items(text)
        assert len(items) == 2
        assert items[0]["name"] == "UK iPhone 12 64GB"
        assert items[0]["price"] == 290000
        assert items[1]["name"] == "UK iPhone 12 128GB"
        assert items[1]["price"] == 330000

    def test_colon_naira_format(self):
        text = "1. UK iPhone 12 128GB + eSIM: \u20a6330,000\n2. UK 12 Pro 128GB: \u20a6400,000"
        items = _extract_numbered_items(text)
        assert len(items) == 2
        assert items[0]["price"] == 330000
        assert items[1]["price"] == 400000

    def test_em_dash_format(self):
        text = "1. Milo Tin \u2013 N3,500\n2. Garri \u2013 N2,500"
        items = _extract_numbered_items(text)
        assert len(items) == 2

    def test_no_comma_in_price(self):
        text = "1. Rice 50kg - N63000"
        items = _extract_numbered_items(text)
        assert len(items) == 1
        assert items[0]["price"] == 63000

    def test_multiple_items(self):
        text = (
            "1. UK 14 Pro Max + eSIM - N800,000\n"
            "2. UK 14 Pro Max 256GB + eSIM - N820,000\n"
            "3. UK 14 Pro Max 512GB + eSIM - N850,000\n"
            "4. iPhone 14 128GB + eSIM - N500,000\n"
            "5. UK 13 Pro 128GB - N500,000"
        )
        items = _extract_numbered_items(text)
        assert len(items) == 5
        assert items[0]["index"] == 1
        assert items[4]["index"] == 5

    def test_no_match_bullet_points(self):
        """Bullet points without numbers should not match."""
        text = "- iPhone 12 64GB: N290,000\n- iPhone 12 128GB: N330,000"
        items = _extract_numbered_items(text)
        assert len(items) == 0

    def test_paragraph_no_match(self):
        """Plain text without numbered format should not match."""
        text = "We have iPhone 12 for N290,000 and iPhone 12 128GB for N330,000"
        items = _extract_numbered_items(text)
        assert len(items) == 0

    def test_empty_text(self):
        items = _extract_numbered_items("")
        assert items == []


class TestQuickPick:
    """Test the quick-pick logic (number → item mapping)."""

    def _pick(self, numbered_items: list[dict], num: int) -> dict | None:
        return next((it for it in numbered_items if it["index"] == num), None)

    def test_pick_valid_number(self):
        items = [
            {"index": 1, "name": "iPhone 12 64GB", "price": 290000},
            {"index": 2, "name": "iPhone 12 128GB", "price": 330000},
        ]
        picked = self._pick(items, 2)
        assert picked is not None
        assert picked["name"] == "iPhone 12 128GB"

    def test_pick_invalid_number(self):
        items = [
            {"index": 1, "name": "iPhone 12 64GB", "price": 290000},
            {"index": 2, "name": "iPhone 12 128GB", "price": 330000},
        ]
        picked = self._pick(items, 5)
        assert picked is None

    def test_pick_first_item(self):
        items = [
            {"index": 1, "name": "Milo", "price": 3500},
            {"index": 2, "name": "Garri", "price": 2500},
            {"index": 3, "name": "Rice", "price": 63000},
        ]
        picked = self._pick(items, 1)
        assert picked["name"] == "Milo"

    def test_pick_last_item(self):
        items = [{"index": i, "name": f"Product {i}", "price": i * 1000} for i in range(1, 9)]
        picked = self._pick(items, 8)
        assert picked["name"] == "Product 8"


class TestClarificationSession:
    """Test that clarification context is stored and retrieved correctly."""

    @pytest.mark.asyncio
    async def test_save_and_get_last_clarification(self, fake_redis):
        from app.modules.orders.session import (
            get_last_clarification,
            save_last_clarification,
        )
        await save_last_clarification("tenant-1", "234", {
            "original_message": "I want iphone",
            "bot_reply": "1. iPhone 12 - N290,000\n2. iPhone 14 - N500,000",
            "numbered_items": [
                {"index": 1, "name": "iPhone 12", "price": 290000},
                {"index": 2, "name": "iPhone 14", "price": 500000},
            ],
        })
        result = await get_last_clarification("tenant-1", "234")
        assert result is not None
        assert result["original_message"] == "I want iphone"
        assert len(result["numbered_items"]) == 2

    @pytest.mark.asyncio
    async def test_last_clarification_returns_none_when_empty(self, fake_redis):
        from app.modules.orders.session import get_last_clarification
        result = await get_last_clarification("tenant-1", "unknown")
        assert result is None

    @pytest.mark.asyncio
    async def test_clear_last_clarification(self, fake_redis):
        from app.modules.orders.session import (
            clear_last_clarification,
            get_last_clarification,
            save_last_clarification,
        )
        await save_last_clarification("tenant-1", "234", {"bot_reply": "test"})
        await clear_last_clarification("tenant-1", "234")
        result = await get_last_clarification("tenant-1", "234")
        assert result is None


class TestOrderSession:
    """Test order session CRUD with fakeredis."""

    @pytest.mark.asyncio
    async def test_set_and_get_session(self, fake_redis):
        from app.modules.orders.session import get_order_session, set_order_session
        await set_order_session("tenant-1", "234", {
            "state": "awaiting_customer_confirmation",
            "order_id": "order-1",
            "items": [{"name": "Rice", "qty": 1, "unit_price": 63000}],
            "total": 63000,
        })
        session = await get_order_session("tenant-1", "234")
        assert session is not None
        assert session["state"] == "awaiting_customer_confirmation"
        assert session["total"] == 63000

    @pytest.mark.asyncio
    async def test_clear_session(self, fake_redis):
        from app.modules.orders.session import (
            clear_order_session,
            get_order_session,
            set_order_session,
        )
        await set_order_session("tenant-1", "234", {"state": "test"})
        await clear_order_session("tenant-1", "234")
        session = await get_order_session("tenant-1", "234")
        assert session is None

    @pytest.mark.asyncio
    async def test_overwrite_session(self, fake_redis):
        from app.modules.orders.session import get_order_session, set_order_session
        await set_order_session("tenant-1", "234", {"state": "first"})
        await set_order_session("tenant-1", "234", {"state": "second"})
        session = await get_order_session("tenant-1", "234")
        assert session["state"] == "second"
