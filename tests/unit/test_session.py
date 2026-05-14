"""
Unit tests for app/modules/orders/session.py

Tests constants, TTL values, and state labels.
No Redis connection needed — just checking the configuration values.
"""

from app.modules.orders.session import (
    AWAITING_CLARIFICATION,
    AWAITING_CUSTOMER_CONFIRMATION,
    TRADER_AWAITING_ADD,
    TRADER_AWAITING_BANK_CONFIRM,
    TRADER_AWAITING_BANK_DETAILS,
    TRADER_AWAITING_COUNTER_PRICE,
    TRADER_AWAITING_CREDIT_PARTIAL,
    TRADER_AWAITING_PHOTO_PRODUCT,
    TRADER_AWAITING_PRICE_SELECT,
    TRADER_AWAITING_PRICE_VALUE,
    TRADER_AWAITING_PRICELIST_CONFIRM,
    TRADER_AWAITING_PRICELIST_PHOTO,
    TRADER_AWAITING_REMOVE,
    _CUSTOMER_ROUTING_TTL,
    _LAST_CLARIFY_TTL,
    _QUIET_TTL,
    _SESSION_TTL,
)


class TestTTLValues:
    def test_routing_ttl_is_7_days(self):
        assert _CUSTOMER_ROUTING_TTL == 7 * 24 * 60 * 60

    def test_quiet_mode_ttl_is_30_min(self):
        assert _QUIET_TTL == 30 * 60

    def test_session_ttl_is_24h(self):
        assert _SESSION_TTL == 24 * 60 * 60

    def test_last_clarify_ttl_is_10_min(self):
        assert _LAST_CLARIFY_TTL == 10 * 60


class TestStateConstants:
    def test_customer_session_states_unique(self):
        states = [AWAITING_CUSTOMER_CONFIRMATION, AWAITING_CLARIFICATION]
        assert len(states) == len(set(states))

    def test_trader_session_states_unique(self):
        states = [
            TRADER_AWAITING_ADD,
            TRADER_AWAITING_REMOVE,
            TRADER_AWAITING_PRICE_SELECT,
            TRADER_AWAITING_PRICE_VALUE,
            TRADER_AWAITING_PRICELIST_PHOTO,
            TRADER_AWAITING_PRICELIST_CONFIRM,
            TRADER_AWAITING_COUNTER_PRICE,
            TRADER_AWAITING_BANK_DETAILS,
            TRADER_AWAITING_BANK_CONFIRM,
            TRADER_AWAITING_CREDIT_PARTIAL,
            TRADER_AWAITING_PHOTO_PRODUCT,
        ]
        assert len(states) == len(set(states))

    def test_all_states_are_strings(self):
        states = [
            AWAITING_CUSTOMER_CONFIRMATION,
            AWAITING_CLARIFICATION,
            TRADER_AWAITING_ADD,
            TRADER_AWAITING_REMOVE,
            TRADER_AWAITING_PRICE_SELECT,
            TRADER_AWAITING_PRICE_VALUE,
            TRADER_AWAITING_PRICELIST_PHOTO,
            TRADER_AWAITING_PRICELIST_CONFIRM,
            TRADER_AWAITING_COUNTER_PRICE,
            TRADER_AWAITING_BANK_DETAILS,
            TRADER_AWAITING_BANK_CONFIRM,
            TRADER_AWAITING_CREDIT_PARTIAL,
            TRADER_AWAITING_PHOTO_PRODUCT,
        ]
        for state in states:
            assert isinstance(state, str)
            assert len(state) > 0
