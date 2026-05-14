"""
Unit tests for app/modules/orders/state_machine.py

Tests valid/invalid order state transitions.
PAID is now terminal (COMPLETED was removed).
"""

import pytest

from app.modules.orders.models import OrderState
from app.modules.orders.state_machine import InvalidTransitionError, validate_transition


class TestValidTransitions:
    def test_inquiry_to_confirmed(self):
        validate_transition("order-1", OrderState.INQUIRY, OrderState.CONFIRMED)

    def test_inquiry_to_failed(self):
        validate_transition("order-1", OrderState.INQUIRY, OrderState.FAILED)

    def test_confirmed_to_paid(self):
        validate_transition("order-1", OrderState.CONFIRMED, OrderState.PAID)

    def test_confirmed_to_failed(self):
        validate_transition("order-1", OrderState.CONFIRMED, OrderState.FAILED)


class TestTerminalStates:
    def test_paid_is_terminal(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("order-1", OrderState.PAID, OrderState.FAILED)

    def test_paid_to_paid_rejected(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("order-1", OrderState.PAID, OrderState.PAID)

    def test_failed_is_terminal(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("order-1", OrderState.FAILED, OrderState.INQUIRY)


class TestInvalidTransitions:
    def test_skip_state_rejected(self):
        """Cannot jump from INQUIRY straight to PAID."""
        with pytest.raises(InvalidTransitionError):
            validate_transition("order-1", OrderState.INQUIRY, OrderState.PAID)

    def test_same_state_rejected(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("order-1", OrderState.CONFIRMED, OrderState.CONFIRMED)

    def test_invalid_state_string(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition("order-1", "nonexistent", OrderState.PAID)


class TestCompletedRemoved:
    def test_completed_not_in_enum(self):
        """COMPLETED was removed from OrderState."""
        values = [s.value for s in OrderState]
        assert "completed" not in values

    def test_order_states_are_four(self):
        """Only 4 states: inquiry, confirmed, paid, failed."""
        assert len(OrderState) == 4
        assert set(s.value for s in OrderState) == {"inquiry", "confirmed", "paid", "failed"}
