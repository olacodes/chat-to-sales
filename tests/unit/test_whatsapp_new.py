"""
Unit tests for new WhatsApp templates: broadcast, follow-up, WHO IS.
"""

import pytest

import app.modules.orders.whatsapp as wa


# ── Broadcast templates ──────────────────────────────────────────────────────


class TestBroadcastSegmentPicker:
    def test_zero_customers(self):
        body, btn, sections = wa.broadcast_segment_picker({"all_customers": 0})
        assert "no customers" in body.lower()

    def test_one_segment(self):
        body, btn, sections = wa.broadcast_segment_picker({
            "all_customers": 5,
            "repeat_buyer": 3,
        })
        assert "5 customers" in body
        assert btn == "Select audience"
        rows = sections[0]["rows"]
        ids = [r["id"] for r in rows]
        assert "BCSEG_all_customers" in ids
        assert "BCSEG_repeat_buyer" in ids

    def test_empty_segments_excluded(self):
        body, btn, sections = wa.broadcast_segment_picker({
            "all_customers": 2,
            "vip": 0,
            "paid_once": 2,
        })
        rows = sections[0]["rows"]
        ids = [r["id"] for r in rows]
        assert "BCSEG_vip" not in ids
        assert "BCSEG_paid_once" in ids

    def test_max_10_rows(self):
        counts = {"all_customers": 100}
        # Add 15 segments
        for seg in ["vip", "repeat_buyer", "paid_once", "new_lead", "lapsed",
                     "abandoned_cart", "diverse_buyer", "price_sensitive",
                     "premium", "weekly", "monthly", "payday", "weekend",
                     "browsed_only"]:
            counts[seg] = 5
        body, btn, sections = wa.broadcast_segment_picker(counts)
        rows = sections[0]["rows"]
        assert len(rows) <= 10


class TestBroadcastCompose:
    def test_compose_prompt(self):
        text = wa.broadcast_compose_prompt("VIP Customers", 10)
        assert "VIP Customers" in text
        assert "10 customers" in text

    def test_compose_singular(self):
        text = wa.broadcast_compose_prompt("Premium", 1)
        assert "1 customer" in text


class TestBroadcastPreview:
    def test_preview_format(self):
        body, buttons = wa.broadcast_preview("Hello everyone!", "All", 5)
        assert "Hello everyone!" in body
        assert "5" in body
        assert len(buttons) == 2
        assert buttons[0]["id"] == "BCYES"
        assert buttons[1]["id"] == "BCNO"


class TestBroadcastProgress:
    def test_progress(self):
        text = wa.broadcast_progress(10, 50)
        assert "10/50" in text
        assert "20%" in text

    def test_complete(self):
        text = wa.broadcast_complete(45, 50, skipped=5)
        assert "45" in text
        assert "5 skipped" in text

    def test_complete_no_skips(self):
        text = wa.broadcast_complete(10, 10)
        assert "skipped" not in text.lower()


class TestBroadcastAntiSpam:
    def test_segment_cooldown(self):
        text = wa.broadcast_segment_cooldown("VIP Customers", 23)
        assert "VIP Customers" in text
        assert "23 hours" in text

    def test_skip_warning(self):
        text = wa.broadcast_skip_warning("All Customers", 50, 10, 40)
        assert "10" in text
        assert "40" in text

    def test_wide_audience_warning(self):
        body, buttons = wa.broadcast_wide_audience_warning(150, "All Customers")
        assert "150" in body
        assert buttons[0]["id"] == "BCWIDEYES"


# ── Follow-up templates ──────────────────────────────────────────────────────


class TestFollowUpTemplates:
    def test_followup_to_customer_with_name(self):
        text = wa.followup_to_customer("Bimpe", "iPhone 12", 330000, "Ola Phones")
        assert "Bimpe" in text
        assert "iPhone 12" in text
        assert "N330,000" in text
        assert "Ola Phones" in text
        assert "YES" in text

    def test_followup_to_customer_no_name(self):
        text = wa.followup_to_customer(None, "Garri 50kg", 2500, "Mama Caro")
        assert "Hi there!" in text
        assert "Garri 50kg" in text

    def test_followup_to_customer_no_price(self):
        text = wa.followup_to_customer("Ade", "Custom item", None, "Trader")
        assert "Custom item" in text
        assert "N" not in text.split("Custom item")[1].split("\n")[0]  # no price after product

    def test_followup_notification_to_trader(self):
        text = wa.followup_notification_to_trader("Bimpe", "2348012345678", "iPhone 12")
        assert "Bimpe" in text
        assert "iPhone 12" in text

    def test_followup_notification_no_name(self):
        text = wa.followup_notification_to_trader(None, "2348012345678", "Garri")
        assert "+2348012345678" in text

    def test_followup_converted(self):
        text = wa.followup_converted_to_trader("Bimpe", "2348012345678", "iPhone 12")
        assert "Bimpe" in text
        assert "iPhone 12" in text


# ── WHO IS templates ─────────────────────────────────────────────────────────


class TestWhoIsTemplates:
    def test_full_result(self):
        text = wa.who_is_result(
            customer_name="Bimpe Adeyemi",
            customer_phone="2348012345678",
            total_orders=5,
            total_spend=150000,
            first_order_date="Jan 10, 2026",
            last_order_date="May 10, 2026",
            segments=["vip", "weekend"],
            outstanding_debt=25000,
        )
        assert "Bimpe Adeyemi" in text
        assert "2348012345678" in text
        assert "5" in text
        assert "N150,000" in text
        assert "Jan 10, 2026" in text
        assert "May 10, 2026" in text
        assert "N25,000" in text
        assert "VIP" in text
        assert "Weekend Shopper" in text

    def test_no_name(self):
        text = wa.who_is_result(
            customer_name=None,
            customer_phone="2348012345678",
            total_orders=1,
            total_spend=5000,
            first_order_date=None,
            last_order_date=None,
            segments=[],
        )
        assert "+2348012345678" in text
        assert "First order" not in text

    def test_no_debt(self):
        text = wa.who_is_result(
            customer_name="Ade",
            customer_phone="234801",
            total_orders=2,
            total_spend=10000,
            first_order_date="Jan 1, 2026",
            last_order_date="Feb 1, 2026",
            segments=["repeat_buyer"],
            outstanding_debt=0,
        )
        assert "debt" not in text.lower()

    def test_not_found(self):
        text = wa.who_is_not_found("Unknown Person")
        assert "Unknown Person" in text
        assert "No customer found" in text
