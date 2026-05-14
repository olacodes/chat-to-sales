"""
Unit tests for app/modules/orders/nlp.py

Tests Layer 1 (regex-based) intent detection only.
No external API calls — pure function tests.
"""

import pytest

from app.modules.orders.nlp import (
    CANCEL,
    CONFIRM,
    IGNORE,
    NEGOTIATION,
    ORDER,
    PAYMENT_SENT,
    TRADER_ADD,
    TRADER_BANK,
    TRADER_CANCEL,
    TRADER_CATALOGUE,
    TRADER_CATEGORY,
    TRADER_CONFIRM,
    TRADER_CREDIT,
    TRADER_DEBT,
    TRADER_MENU,
    TRADER_ORDERS,
    TRADER_PAID,
    TRADER_PAID_DEBT,
    TRADER_PRICE,
    TRADER_PRICELIST,
    TRADER_REMOVE,
    TRADER_WHO_OWES_ME,
    UNKNOWN,
    _layer1,
    _parse_add_items,
)


# ── Customer YES / NO ────────────────────────────────────────────────────────


class TestCustomerYesNo:
    @pytest.mark.parametrize("msg", ["yes", "yep", "yeah", "ok", "okay", "oya", "correct", "sure", "go ahead"])
    def test_confirm_yes_variants(self, msg: str):
        result = _layer1(msg)
        assert result.intent == CONFIRM
        assert result.confidence == 1.0

    @pytest.mark.parametrize("msg", ["no", "nope", "cancel", "stop", "forget am", "forget it", "abeg cancel"])
    def test_cancel_no_variants(self, msg: str):
        result = _layer1(msg)
        assert result.intent == CANCEL
        assert result.confidence == 1.0


# ── Trader Commands ──────────────────────────────────────────────────────────


class TestTraderCommands:
    def test_trader_confirm_command(self):
        result = _layer1("CONFIRM abc123de")
        assert result.intent == TRADER_CONFIRM
        assert result.order_ref == "abc123de"
        assert result.confidence == 1.0

    def test_trader_cancel_command(self):
        result = _layer1("CANCEL abc123de")
        assert result.intent == TRADER_CANCEL
        assert result.order_ref == "abc123de"

    def test_trader_paid_command(self):
        result = _layer1("PAID abc123de")
        assert result.intent == TRADER_PAID
        assert result.order_ref == "abc123de"

    def test_trader_credit_command(self):
        result = _layer1("CREDIT abc123de")
        assert result.intent == TRADER_CREDIT
        assert result.order_ref == "abc123de"

    def test_delivered_command_removed(self):
        """DELIVERED was removed — should NOT match as a trader command."""
        result = _layer1("DELIVERED abc123de")
        assert result.intent != "trader_delivered"

    def test_case_insensitive(self):
        result = _layer1("confirm ABC123DE")
        assert result.intent == TRADER_CONFIRM
        assert result.order_ref == "abc123de"


# ── Catalogue Management ─────────────────────────────────────────────────────


class TestCatalogueCommands:
    def test_add_single_product(self):
        result = _layer1("ADD Milo 3500")
        assert result.intent == TRADER_ADD
        assert len(result.items) == 1
        assert result.items[0]["name"] == "Milo"
        assert result.items[0]["unit_price"] == 3500

    def test_add_batch_products(self):
        result = _layer1("ADD Milo 3500, Garri 2500, Rice 63000")
        assert result.intent == TRADER_ADD
        assert len(result.items) == 3

    def test_add_comma_in_price(self):
        items = _parse_add_items("ADD Milo 3,500, Garri 2,500")
        assert len(items) == 2
        assert items[0]["unit_price"] == 3500
        assert items[1]["unit_price"] == 2500

    def test_remove_single(self):
        result = _layer1("REMOVE Garri")
        assert result.intent == TRADER_REMOVE
        assert len(result.items) == 1
        assert result.items[0]["name"] == "Garri"

    def test_remove_batch(self):
        result = _layer1("REMOVE Garri, Milo, Rice")
        assert result.intent == TRADER_REMOVE
        assert len(result.items) == 3

    def test_price_update(self):
        result = _layer1("PRICE Rice 75000")
        assert result.intent == TRADER_PRICE
        assert result.items[0]["unit_price"] == 75000

    def test_price_batch(self):
        result = _layer1("PRICE Rice 75000, Milo 4000")
        assert result.intent == TRADER_PRICE
        assert len(result.items) == 2

    def test_catalogue_command(self):
        result = _layer1("CATALOGUE")
        assert result.intent == TRADER_CATALOGUE

    def test_catalogue_alias(self):
        result = _layer1("my products")
        assert result.intent == TRADER_CATALOGUE

    def test_pricelist_command(self):
        result = _layer1("price list")
        assert result.intent == TRADER_PRICELIST

    def test_category_command(self):
        result = _layer1("CATEGORY")
        assert result.intent == TRADER_CATEGORY


# ── Menu / Navigation ────────────────────────────────────────────────────────


class TestMenuCommands:
    def test_menu_command(self):
        result = _layer1("MENU")
        assert result.intent == TRADER_MENU

    def test_help_command(self):
        result = _layer1("help")
        assert result.intent == TRADER_MENU

    def test_bank_command(self):
        result = _layer1("BANK")
        assert result.intent == TRADER_BANK

    def test_orders_command(self):
        result = _layer1("ORDERS")
        assert result.intent == TRADER_ORDERS

    def test_who_owes_me(self):
        result = _layer1("WHO OWES ME")
        assert result.intent == TRADER_WHO_OWES_ME

    def test_debts_alias(self):
        result = _layer1("debts")
        assert result.intent == TRADER_WHO_OWES_ME


# ── Debt Commands ────────────────────────────────────────────────────────────


class TestDebtCommands:
    def test_debt_command(self):
        result = _layer1("DEBT Iya Bimpe 5000")
        assert result.intent == TRADER_DEBT
        assert result.items[0]["name"] == "Iya Bimpe"
        assert result.items[0]["unit_price"] == 5000

    def test_paid_debt_command(self):
        """PAID + name (starts with letter) = debt settlement, not order command."""
        result = _layer1("PAID Iya Bimpe 5000")
        assert result.intent == TRADER_PAID_DEBT
        assert result.items[0]["name"] == "Iya Bimpe"
        assert result.items[0]["unit_price"] == 5000

    def test_paid_hex_ref_is_order_command(self):
        """PAID + hex ref = order PAID command, not debt settlement."""
        result = _layer1("PAID abc123de")
        assert result.intent == TRADER_PAID
        assert result.order_ref == "abc123de"


# ── Payment Detection ────────────────────────────────────────────────────────


class TestPaymentDetection:
    @pytest.mark.parametrize("msg", [
        "paid",
        "I've paid",
        "I have paid",
        "payment sent",
        "payment done",
        "payment completed",
        "transferred",
        "sent the money",
        "money sent",
        "already paid",
        "already sent",
        "done the payment",
        "check your account",
        "check account",
        "receipt",
        "proof of payment",
    ])
    def test_payment_sent_variants(self, msg: str):
        result = _layer1(msg)
        assert result.intent == PAYMENT_SENT, f"Expected PAYMENT_SENT for '{msg}', got {result.intent}"

    @pytest.mark.parametrize("msg", [
        "e don pay",
        "don pay",
        "i pay am",
    ])
    def test_payment_sent_pidgin(self, msg: str):
        result = _layer1(msg)
        assert result.intent == PAYMENT_SENT, f"Expected PAYMENT_SENT for '{msg}', got {result.intent}"


# ── Negotiation Detection ────────────────────────────────────────────────────


class TestNegotiationDetection:
    def test_negotiation_specific_price(self):
        result = _layer1("can you do 5000?")
        assert result.intent == NEGOTIATION
        assert result.items[0]["unit_price"] == 5000

    def test_negotiation_with_naira(self):
        result = _layer1("I'll pay N5,000")
        assert result.intent == NEGOTIATION
        assert result.items[0]["unit_price"] == 5000

    @pytest.mark.parametrize("msg", [
        "too expensive",
        "too much",
        "any discount?",
        "cheaper",
        "reduce the price",
        "best price",
        "last price",
        "not affordable",
    ])
    def test_negotiation_general(self, msg: str):
        result = _layer1(msg)
        assert result.intent == NEGOTIATION, f"Expected NEGOTIATION for '{msg}', got {result.intent}"


# ── Order Intent ─────────────────────────────────────────────────────────────


class TestOrderIntent:
    def test_order_with_trigger_and_product(self):
        result = _layer1("I want 2 bags of rice")
        assert result.intent == ORDER
        assert len(result.items) >= 1
        assert result.confidence == 0.7

    def test_order_without_trigger_goes_unknown(self):
        """'2 bags of rice' has no trigger word (want/buy/order) — Layer 1 returns UNKNOWN."""
        result = _layer1("2 bags of rice")
        assert result.intent == UNKNOWN

    def test_order_keywords_only(self):
        result = _layer1("I want to buy something")
        assert result.intent == ORDER
        assert result.confidence == 0.3

    def test_unknown_no_keywords(self):
        result = _layer1("pick up the kids at 3pm")
        assert result.intent == UNKNOWN
        assert result.confidence == 0.0

    def test_yoruba_numbers_with_trigger(self):
        result = _layer1("I want meji bags of rice")
        assert result.intent == ORDER
        assert result.items[0]["qty"] == 2
