"""
Unit tests for app/modules/orders/whatsapp.py

Tests WhatsApp message template output — customer name fallback,
button IDs, message formatting.
"""

import pytest

from app.modules.orders.whatsapp import (
    _customer_label,
    _naira,
    bank_verify_confirm,
    credit_paid_in_full,
    credit_partial_received,
    credit_partial_prompt,
    order_action_buttons,
    order_already_on_credit,
    order_cancelled_to_trader,
    order_confirmed_to_trader,
    order_credit_buttons,
    order_credit_to_trader,
    order_paid_to_trader,
    order_received_interactive,
    order_reminder_to_trader,
    payment_receipt_to_trader,
    pending_order_actions,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


class TestHelpers:
    def test_naira_formatting(self):
        assert _naira(850000) == "N850,000"

    def test_naira_zero(self):
        assert _naira(0) == "N0"

    def test_naira_small(self):
        assert _naira(500) == "N500"

    def test_customer_label_with_name(self):
        assert _customer_label("Sodiq Olatunde", "2348166041471") == "*Sodiq Olatunde*"

    def test_customer_label_no_name(self):
        assert _customer_label(None, "2348166041471") == "+2348166041471"

    def test_customer_label_empty_name(self):
        assert _customer_label("", "2348166041471") == "+2348166041471"


# ── Order Confirmed ──────────────────────────────────────────────────────────


class TestOrderConfirmed:
    def test_order_confirmed_with_name(self):
        body, buttons = order_confirmed_to_trader("abc123", customer_name="Sodiq", customer_phone="234")
        assert "*Sodiq*" in body
        assert "+234" not in body

    def test_order_confirmed_no_name(self):
        body, buttons = order_confirmed_to_trader("abc123", customer_name=None, customer_phone="2348166041471")
        assert "+2348166041471" in body

    def test_order_confirmed_buttons(self):
        _, buttons = order_confirmed_to_trader("abc123")
        ids = [b["id"] for b in buttons]
        assert "PAID abc123" in ids
        assert "CREDIT abc123" in ids


# ── Order Cancelled / Paid / Delivered ────────────────────────────────────────


class TestOrderStatusMessages:
    def test_cancelled_with_name(self):
        text = order_cancelled_to_trader("abc123", customer_name="Sodiq")
        assert "*Sodiq*" in text

    def test_cancelled_no_name(self):
        text = order_cancelled_to_trader("abc123", customer_name=None)
        assert "abc123" in text

    def test_paid_with_name(self):
        text = order_paid_to_trader("abc123", customer_name="Sodiq")
        assert "*Sodiq*" in text

    def test_order_reminder_with_name(self):
        body, buttons = order_reminder_to_trader(
            "2348166041471", 50000, "abc123", 2, customer_name="Sodiq",
        )
        assert "*Sodiq*" in body
        assert "+2348166041471" not in body


# ── Credit Flow ──────────────────────────────────────────────────────────────


class TestCreditTemplates:
    def test_credit_buttons_format(self):
        body, buttons = order_credit_buttons("abc123", "Sodiq", 820000)
        ids = [b["id"] for b in buttons]
        assert "CREDITPAID abc123" in ids
        assert "CREDITPART abc123" in ids
        assert "*Sodiq*" in body

    def test_already_on_credit_with_name(self):
        text = order_already_on_credit("abc123", customer_name="Sodiq")
        assert "*Sodiq*" in text

    def test_already_on_credit_no_name(self):
        text = order_already_on_credit("abc123", customer_name=None)
        assert "abc123" in text

    def test_credit_partial_prompt_with_name(self):
        text = credit_partial_prompt("abc123", 770000, customer_name="Sodiq")
        assert "*Sodiq*" in text
        assert "N770,000" in text

    def test_credit_paid_in_full_with_name(self):
        text = credit_paid_in_full("abc123", 820000, customer_name="Sodiq")
        assert "*Sodiq*" in text
        assert "N820,000" in text

    def test_credit_partial_received_with_name(self):
        text = credit_partial_received("abc123", 50000, 770000, customer_name="Sodiq")
        assert "*Sodiq*" in text
        assert "N50,000" in text
        assert "N770,000" in text

    def test_credit_to_trader(self):
        text = order_credit_to_trader("abc123", "Sodiq", 600000)
        assert "*Sodiq*" in text
        assert "N600,000" in text


# ── Order Action Buttons ─────────────────────────────────────────────────────


class TestOrderActionButtons:
    def test_pending_non_credit_buttons(self):
        body, buttons = pending_order_actions("abc123", "Sodiq", 500000, is_credit=False)
        ids = [b["id"] for b in buttons]
        assert "PAID abc123" in ids
        assert "CREDIT abc123" in ids

    def test_pending_credit_buttons(self):
        body, buttons = pending_order_actions("abc123", "Sodiq", 500000, is_credit=True)
        ids = [b["id"] for b in buttons]
        assert "CREDITPAID abc123" in ids
        assert "CREDITPART abc123" in ids

    def test_action_buttons_inquiry(self):
        body, buttons = order_action_buttons("abc123", "Sodiq", 500000, "inquiry", False)
        ids = [b["id"] for b in buttons]
        assert "CONFIRM abc123" in ids
        assert "CANCEL abc123" in ids

    def test_action_buttons_confirmed_credit(self):
        body, buttons = order_action_buttons("abc123", "Sodiq", 500000, "confirmed", True)
        ids = [b["id"] for b in buttons]
        assert "CREDITPAID abc123" in ids
        assert "CREDITPART abc123" in ids

    def test_action_buttons_paid_no_buttons(self):
        """PAID is terminal — no action buttons."""
        body, buttons = order_action_buttons("abc123", "Sodiq", 500000, "paid", False)
        assert buttons == []


# ── Payment Receipt ──────────────────────────────────────────────────────────


class TestPaymentReceipt:
    def test_payment_receipt_with_name(self):
        body, buttons = payment_receipt_to_trader("234", "Sodiq", 85000, "abc123")
        assert "*Sodiq*" in body
        assert "N85,000" in body

    def test_payment_receipt_with_screenshot(self):
        body, _ = payment_receipt_to_trader("234", "Sodiq", 85000, "abc123", has_screenshot=True)
        assert "screenshot" in body.lower()

    def test_payment_receipt_buttons(self):
        _, buttons = payment_receipt_to_trader("234", "Sodiq", 85000, "abc123")
        ids = [b["id"] for b in buttons]
        assert "PAYRCVD abc123" in ids
        assert "PAYNOTRCVD abc123" in ids


# ── Bank Verification ────────────────────────────────────────────────────────


class TestBankVerification:
    def test_bank_verify_confirm_format(self):
        body, buttons = bank_verify_confirm("GTBank", "0123456789", "OLATUNDE SODIQ")
        assert "GTBank" in body
        assert "0123456789" in body
        assert "OLATUNDE SODIQ" in body
        ids = [b["id"] for b in buttons]
        assert "BANK_YES" in ids
        assert "BANK_NO" in ids


# ── New Order Notification ───────────────────────────────────────────────────


class TestOrderReceived:
    def test_order_received_with_name(self):
        body, buttons = order_received_interactive(
            items=[{"name": "Rice", "qty": 2, "unit_price": 63000}],
            total=126000,
            customer_phone="2348166041471",
            order_ref="abc123",
            customer_name="Sodiq",
        )
        assert "*Sodiq*" in body
        assert "+2348166041471" not in body

    def test_order_received_no_name(self):
        body, buttons = order_received_interactive(
            items=[{"name": "Rice", "qty": 1, "unit_price": 63000}],
            total=63000,
            customer_phone="2348166041471",
            order_ref="abc123",
            customer_name=None,
        )
        assert "+2348166041471" in body
