"""
Unit tests for new NLP intents: BROADCAST, WHO IS.
"""

import pytest

from app.modules.orders.nlp import (
    TRADER_BROADCAST,
    TRADER_WHO_IS,
    UNKNOWN,
    _layer1,
)


# ── BROADCAST intent ─────────────────────────────────────────────────────────


class TestBroadcastIntent:
    @pytest.mark.parametrize("msg", [
        "broadcast",
        "BROADCAST",
        "Broadcast",
        "send broadcast",
        "Send Broadcast",
        "message all",
        "message customers",
        "blast",
        "BLAST",
    ])
    def test_broadcast_detected(self, msg):
        result = _layer1(msg)
        assert result.intent == TRADER_BROADCAST
        assert result.confidence == 1.0

    @pytest.mark.parametrize("msg", [
        "broadcast this message",  # has trailing text — not an exact match
        "send a broadcast now",
        "I want to broadcast",
    ])
    def test_broadcast_not_detected(self, msg):
        result = _layer1(msg)
        assert result.intent != TRADER_BROADCAST


# ── WHO IS intent ────────────────────────────────────────────────────────────


class TestWhoIsIntent:
    @pytest.mark.parametrize("msg,expected_query", [
        ("who is Bimpe", "Bimpe"),
        ("WHO IS Bimpe", "Bimpe"),
        ("Who Is Mama Tayo", "Mama Tayo"),
        ("who is 08166041471", "08166041471"),
        ("whois Sodiq", "Sodiq"),
        ("who are you selling to Ade", "you selling to Ade"),
    ])
    def test_who_is_detected(self, msg, expected_query):
        result = _layer1(msg)
        assert result.intent == TRADER_WHO_IS
        assert result.confidence == 1.0
        assert result.items[0]["name"] == expected_query

    def test_who_is_preserves_full_name(self):
        result = _layer1("who is Iya Bimpe from Bodija")
        assert result.intent == TRADER_WHO_IS
        assert result.items[0]["name"] == "Iya Bimpe from Bodija"

    @pytest.mark.parametrize("msg", [
        "who",
        "who is",      # no query after "who is"
        "is Bimpe",
    ])
    def test_who_is_not_detected(self, msg):
        result = _layer1(msg)
        assert result.intent != TRADER_WHO_IS
