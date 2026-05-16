"""
Unit tests for app/modules/marketing/segments.py — segment computation.
"""

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.modules.marketing.segments import (
    _compute_behaviour_segment,
    _compute_interest_segments,
    _compute_timing_segments,
)


NOW = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)


# ── Behaviour segments ───────────────────────────────────────────────────────


class TestBehaviourSegment:
    def test_new_lead_zero_orders(self):
        assert _compute_behaviour_segment(0, Decimal("0"), None, False, NOW) == "new_lead"

    def test_abandoned_cart(self):
        assert _compute_behaviour_segment(0, Decimal("0"), None, True, NOW) == "abandoned_cart"

    def test_paid_once(self):
        last = NOW - timedelta(days=10)
        assert _compute_behaviour_segment(1, Decimal("5000"), last, False, NOW) == "paid_once"

    def test_repeat_buyer(self):
        last = NOW - timedelta(days=5)
        assert _compute_behaviour_segment(3, Decimal("15000"), last, False, NOW) == "repeat_buyer"

    def test_vip_by_orders(self):
        last = NOW - timedelta(days=2)
        assert _compute_behaviour_segment(5, Decimal("50000"), last, False, NOW) == "vip"

    def test_vip_by_spend(self):
        last = NOW - timedelta(days=10)
        assert _compute_behaviour_segment(2, Decimal("250000"), last, False, NOW) == "vip"

    def test_vip_threshold_exact(self):
        last = NOW - timedelta(days=1)
        assert _compute_behaviour_segment(5, Decimal("200000"), last, False, NOW) == "vip"

    def test_lapsed_from_paid_once(self):
        last = NOW - timedelta(days=91)
        assert _compute_behaviour_segment(1, Decimal("5000"), last, False, NOW) == "lapsed"

    def test_lapsed_from_repeat(self):
        last = NOW - timedelta(days=100)
        assert _compute_behaviour_segment(3, Decimal("30000"), last, False, NOW) == "lapsed"

    def test_lapsed_from_vip(self):
        last = NOW - timedelta(days=95)
        assert _compute_behaviour_segment(10, Decimal("500000"), last, False, NOW) == "lapsed"

    def test_not_lapsed_at_89_days(self):
        last = NOW - timedelta(days=89)
        assert _compute_behaviour_segment(1, Decimal("5000"), last, False, NOW) == "paid_once"

    def test_lapsed_at_90_days(self):
        last = NOW - timedelta(days=90)
        # 90 days is NOT > 90, so should not be lapsed
        assert _compute_behaviour_segment(1, Decimal("5000"), last, False, NOW) == "paid_once"

    def test_lapsed_at_91_days(self):
        last = NOW - timedelta(days=91)
        assert _compute_behaviour_segment(1, Decimal("5000"), last, False, NOW) == "lapsed"

    def test_repeat_buyer_boundary_2_orders(self):
        last = NOW - timedelta(days=5)
        assert _compute_behaviour_segment(2, Decimal("10000"), last, False, NOW) == "repeat_buyer"

    def test_repeat_buyer_boundary_4_orders(self):
        last = NOW - timedelta(days=5)
        assert _compute_behaviour_segment(4, Decimal("40000"), last, False, NOW) == "repeat_buyer"


# ── Interest segments ────────────────────────────────────────────────────────


class TestInterestSegments:
    def test_no_data(self):
        result = _compute_interest_segments([], 0, Decimal("0"), Decimal("0"))
        assert result == []

    def test_diverse_buyer(self):
        items = [{"product_name": f"product_{i}"} for i in range(5)]
        result = _compute_interest_segments(items, 0, Decimal("10000"), Decimal("8000"))
        assert "diverse_buyer" in result

    def test_not_diverse_with_4_products(self):
        items = [{"product_name": f"product_{i}"} for i in range(4)]
        result = _compute_interest_segments(items, 0, Decimal("10000"), Decimal("8000"))
        assert "diverse_buyer" not in result

    def test_price_sensitive(self):
        result = _compute_interest_segments([], 2, Decimal("5000"), Decimal("8000"))
        assert "price_sensitive" in result

    def test_not_price_sensitive_with_1_negotiation(self):
        result = _compute_interest_segments([], 1, Decimal("5000"), Decimal("8000"))
        assert "price_sensitive" not in result

    def test_premium_buyer(self):
        # 1.5x above average, never negotiated
        result = _compute_interest_segments([], 0, Decimal("15000"), Decimal("8000"))
        assert "premium" in result

    def test_not_premium_if_negotiated(self):
        result = _compute_interest_segments([], 1, Decimal("15000"), Decimal("8000"))
        assert "premium" not in result

    def test_not_premium_if_below_threshold(self):
        # 1.4x is below 1.5x threshold
        result = _compute_interest_segments([], 0, Decimal("11200"), Decimal("8000"))
        assert "premium" not in result

    def test_premium_at_exact_threshold(self):
        # Exactly 1.5x
        result = _compute_interest_segments([], 0, Decimal("12000"), Decimal("8000"))
        assert "premium" in result

    def test_zero_trader_avg(self):
        """No crash when trader has no average."""
        result = _compute_interest_segments([], 0, Decimal("10000"), Decimal("0"))
        assert "premium" not in result

    def test_diverse_and_price_sensitive(self):
        items = [{"product_name": f"p{i}"} for i in range(6)]
        result = _compute_interest_segments(items, 3, Decimal("5000"), Decimal("8000"))
        assert "diverse_buyer" in result
        assert "price_sensitive" in result


# ── Timing segments ──────────────────────────────────────────────────────────


class TestTimingSegments:
    def test_no_dates(self):
        assert _compute_timing_segments([]) == []

    def test_single_date(self):
        assert _compute_timing_segments([NOW]) == []

    def test_weekly_pattern(self):
        """Orders every 7 days → weekly."""
        dates = [NOW - timedelta(days=7 * i) for i in range(4)]
        result = _compute_timing_segments(dates)
        assert "weekly" in result

    def test_monthly_pattern(self):
        """Orders every 30 days → monthly."""
        dates = [NOW - timedelta(days=30 * i) for i in range(4)]
        result = _compute_timing_segments(dates)
        assert "monthly" in result

    def test_weekend_pattern(self):
        """All orders on Saturday → weekend."""
        # Find next Saturday from NOW
        days_to_sat = (5 - NOW.weekday()) % 7
        sat = NOW + timedelta(days=days_to_sat)
        dates = [sat - timedelta(weeks=i) for i in range(4)]
        result = _compute_timing_segments(dates)
        assert "weekend" in result

    def test_weekday_pattern_not_weekend(self):
        """All orders on Tuesday → NOT weekend."""
        days_to_tue = (1 - NOW.weekday()) % 7
        tue = NOW + timedelta(days=days_to_tue)
        dates = [tue - timedelta(weeks=i) for i in range(4)]
        result = _compute_timing_segments(dates)
        assert "weekend" not in result

    def test_payday_pattern(self):
        """Orders on 1st of each month → payday."""
        dates = [
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 2, 1, tzinfo=timezone.utc),
            datetime(2026, 3, 1, tzinfo=timezone.utc),
            datetime(2026, 4, 1, tzinfo=timezone.utc),
        ]
        result = _compute_timing_segments(dates)
        assert "payday" in result

    def test_end_of_month_payday(self):
        """Orders on 25th-28th → payday."""
        dates = [
            datetime(2026, 1, 25, tzinfo=timezone.utc),
            datetime(2026, 2, 26, tzinfo=timezone.utc),
            datetime(2026, 3, 27, tzinfo=timezone.utc),
            datetime(2026, 4, 28, tzinfo=timezone.utc),
        ]
        result = _compute_timing_segments(dates)
        assert "payday" in result

    def test_mid_month_not_payday(self):
        """Orders on 10th-15th → NOT payday."""
        dates = [
            datetime(2026, 1, 10, tzinfo=timezone.utc),
            datetime(2026, 2, 12, tzinfo=timezone.utc),
            datetime(2026, 3, 14, tzinfo=timezone.utc),
            datetime(2026, 4, 11, tzinfo=timezone.utc),
        ]
        result = _compute_timing_segments(dates)
        assert "payday" not in result

    def test_mixed_timing(self):
        """Weekly orders on weekends → both weekly and weekend."""
        # Every 7 days, all on Saturdays
        days_to_sat = (5 - NOW.weekday()) % 7
        sat = NOW + timedelta(days=days_to_sat)
        dates = [sat - timedelta(weeks=i) for i in range(5)]
        result = _compute_timing_segments(dates)
        assert "weekly" in result
        assert "weekend" in result
