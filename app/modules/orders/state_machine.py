"""
app/modules/orders/state_machine.py

Strict order state machine for ChatToSales.

Allowed transitions
-------------------
INQUIRY    → CONFIRMED | FAILED
CONFIRMED  → PAID      | FAILED
PAID       → COMPLETED | FAILED
COMPLETED  → (terminal — no further transitions)
FAILED     → (terminal — no further transitions)

ANY attempt to move to a state not in the allowed set raises
InvalidTransitionError, which maps to HTTP 409 in the exception handlers.
"""

from app.core.logging import get_logger
from app.modules.orders.models import OrderState

logger = get_logger(__name__)

# ── Transition table ──────────────────────────────────────────────────────────

_VALID_TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.INQUIRY: frozenset({OrderState.CONFIRMED, OrderState.FAILED}),
    OrderState.CONFIRMED: frozenset({OrderState.PAID, OrderState.COMPLETED, OrderState.FAILED}),
    OrderState.PAID: frozenset({OrderState.COMPLETED, OrderState.FAILED}),
    OrderState.COMPLETED: frozenset(),  # terminal
    OrderState.FAILED: frozenset(),     # terminal
}


# ── Exception ─────────────────────────────────────────────────────────────────


class InvalidTransitionError(Exception):
    """Raised when a requested state transition is not allowed."""

    def __init__(self, order_id: str, from_state: str, to_state: str) -> None:
        self.order_id = order_id
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Order '{order_id}': transition {from_state!r} → {to_state!r} is not allowed."
        )


# ── Core function ─────────────────────────────────────────────────────────────


def validate_transition(order_id: str, current_state: str, new_state: str) -> None:
    """
    Verify that moving from current_state to new_state is permitted.

    Raises InvalidTransitionError on any invalid attempt — including:
    - Transitioning a terminal state (COMPLETED / FAILED) to anything
    - Skipping states (e.g. INQUIRY → PAID)
    - No-op transitions (same state → same state)
    """
    try:
        from_state = OrderState(current_state)
        to_state = OrderState(new_state)
    except ValueError as exc:
        raise InvalidTransitionError(order_id, current_state, new_state) from exc

    if from_state == to_state:
        raise InvalidTransitionError(order_id, current_state, new_state)

    allowed = _VALID_TRANSITIONS.get(from_state, frozenset())
    if to_state not in allowed:
        logger.warning(
            "Invalid transition rejected order_id=%s %s → %s (allowed: %s)",
            order_id,
            current_state,
            new_state,
            {s.value for s in allowed} or "none (terminal state)",
        )
        raise InvalidTransitionError(order_id, current_state, new_state)

    logger.debug(
        "Transition valid order_id=%s %s → %s", order_id, current_state, new_state
    )
