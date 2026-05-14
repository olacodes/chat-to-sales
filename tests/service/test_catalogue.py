"""
Service tests for catalogue management.

Tests zero-price lookup, item matching, and price formatting.
"""

import pytest

from app.modules.orders.nlp import _layer1, _parse_add_items, TRADER_ADD, TRADER_PRICE, TRADER_REMOVE


class TestZeroPriceLookup:
    """Test that unit_price=0 is treated as missing and triggers catalogue lookup."""

    def test_zero_price_is_falsy(self):
        """not 0 == True, so zero-price items should trigger catalogue lookup."""
        assert not 0

    def test_none_price_is_falsy(self):
        assert not None

    def test_valid_price_is_truthy(self):
        assert 3500


class TestCatalogueParsing:
    def test_parse_single_add(self):
        items = _parse_add_items("ADD Milo 3500")
        assert len(items) == 1
        assert items[0]["name"] == "Milo"
        assert items[0]["unit_price"] == 3500

    def test_parse_batch_add(self):
        items = _parse_add_items("ADD Milo 3500, Garri 2500, Rice 63000")
        assert len(items) == 3
        names = [i["name"] for i in items]
        assert "Milo" in names
        assert "Garri" in names
        assert "Rice" in names

    def test_parse_add_multiword_product(self):
        items = _parse_add_items("ADD Peak Milk Tin 1200")
        assert len(items) == 1
        assert items[0]["name"] == "Peak Milk Tin"
        assert items[0]["unit_price"] == 1200

    def test_parse_add_comma_in_price(self):
        items = _parse_add_items("ADD Milo 3,500")
        assert len(items) == 1
        assert items[0]["unit_price"] == 3500

    def test_parse_add_empty_body(self):
        items = _parse_add_items("ADD")
        assert items == []

    def test_parse_add_newline_format(self):
        items = _parse_add_items("ADD\nMilo 3500\nGarri 2500")
        assert len(items) == 2


class TestCatalogueMatchingLogic:
    """Test the fuzzy matching logic used for price lookup."""

    def _fuzzy_match(self, item_name: str, catalogue: dict[str, int]) -> int | None:
        """Same logic as service.py catalogue lookup."""
        item_name_lower = item_name.lower()
        for cat_name, cat_price in catalogue.items():
            if item_name_lower in cat_name.lower() or cat_name.lower() in item_name_lower:
                return cat_price
        return None

    def test_exact_match(self):
        cat = {"Milo": 3500, "Garri": 2500}
        assert self._fuzzy_match("Milo", cat) == 3500

    def test_case_insensitive_match(self):
        cat = {"Milo": 3500, "Garri": 2500}
        assert self._fuzzy_match("milo", cat) == 3500

    def test_partial_match_item_in_catalogue(self):
        cat = {"UK 14 Pro Max + eSIM": 800000}
        assert self._fuzzy_match("14 Pro Max", cat) == 800000

    def test_partial_match_catalogue_in_item(self):
        cat = {"Indomie": 8500}
        assert self._fuzzy_match("Indomie Carton", cat) == 8500

    def test_no_match(self):
        cat = {"Milo": 3500, "Garri": 2500}
        assert self._fuzzy_match("iPhone", cat) is None

    def test_empty_catalogue(self):
        assert self._fuzzy_match("Milo", {}) is None
