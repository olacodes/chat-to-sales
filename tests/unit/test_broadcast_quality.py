"""
Unit tests for app/modules/marketing/broadcast.py — quality checks.
"""

import pytest

from app.modules.marketing.broadcast import check_message_quality


class TestCheckMessageQuality:
    """Tests for the pre-send quality gate."""

    def test_clean_message(self):
        issues = check_message_quality("Hello everyone, we have new stock at great prices today")
        assert issues == []

    def test_too_short(self):
        issues = check_message_quality("Buy now")
        assert any("too short" in i.lower() for i in issues)

    def test_all_caps_flagged(self):
        issues = check_message_quality("BUY NOW FROM OUR STORE TODAY FOR THE BEST DEALS AVAILABLE")
        assert any("caps" in i.lower() for i in issues)

    def test_mixed_case_ok(self):
        """Normal sentence with a few caps words should pass."""
        issues = check_message_quality("Check out our NEW arrivals at Ola Phones today")
        assert not any("caps" in i.lower() for i in issues)

    def test_exclamation_marks_flagged(self):
        issues = check_message_quality("Amazing deals available now!! Come and buy today!!")
        assert any("exclamation" in i.lower() for i in issues)

    def test_single_exclamation_ok(self):
        issues = check_message_quality("We have amazing new stock available today!")
        assert not any("exclamation" in i.lower() for i in issues)

    def test_bitly_flagged(self):
        issues = check_message_quality("Check our store at bit.ly/ola-phones for great deals")
        assert any("shortener" in i.lower() for i in issues)

    def test_tinyurl_flagged(self):
        issues = check_message_quality("Visit tinyurl.com/our-store for the best products today")
        assert any("shortener" in i.lower() for i in issues)

    def test_full_url_ok(self):
        issues = check_message_quality("Visit our store at https://chattosales.com/stores/ola-phones")
        assert not any("shortener" in i.lower() for i in issues)

    def test_spam_phrase_guaranteed(self):
        issues = check_message_quality("Guaranteed lowest prices on all items in our store today")
        assert any("spam" in i.lower() for i in issues)

    def test_spam_phrase_best_price_ever(self):
        issues = check_message_quality("This is the best price ever on this product, grab it now")
        assert any("spam" in i.lower() for i in issues)

    def test_spam_phrase_act_now(self):
        issues = check_message_quality("Act now before the stock runs out, limited quantities today")
        assert any("spam" in i.lower() for i in issues)

    def test_spam_phrase_limited_offer(self):
        issues = check_message_quality("Limited offer on all phones this week, do not miss this")
        assert any("spam" in i.lower() for i in issues)

    def test_multiple_issues(self):
        """A truly spammy message should trigger multiple issues."""
        issues = check_message_quality("BUY NOW!!! GUARANTEED BEST PRICE EVER bit.ly/deal")
        assert len(issues) >= 3

    def test_empty_string(self):
        issues = check_message_quality("")
        assert any("too short" in i.lower() for i in issues)

    def test_whitespace_only(self):
        issues = check_message_quality("   ")
        assert any("too short" in i.lower() for i in issues)

    def test_nigerian_english_ok(self):
        """Natural Nigerian English marketing should pass."""
        issues = check_message_quality(
            "Good morning! Fresh tomatoes just arrived at Mama Caro provisions. "
            "Very fresh and affordable. Come and buy before they finish."
        )
        assert issues == []

    def test_warm_broadcast_ok(self):
        issues = check_message_quality(
            "Hi there, we just restocked our popular items. "
            "Check out what is new at Ola Phones. Thank you for your patronage."
        )
        assert issues == []
