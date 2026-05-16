"""
Unit tests for app/modules/marketing/followup.py — interest event model + enum.
"""

import pytest

from app.modules.marketing.followup import InterestType


class TestInterestType:
    def test_price_inquiry(self):
        assert InterestType.PRICE_INQUIRY == "price_inquiry"

    def test_image_inquiry(self):
        assert InterestType.IMAGE_INQUIRY == "image_inquiry"

    def test_order_cancelled(self):
        assert InterestType.ORDER_CANCELLED == "order_cancelled"

    def test_all_values(self):
        values = {e.value for e in InterestType}
        assert values == {"price_inquiry", "image_inquiry", "order_cancelled"}
