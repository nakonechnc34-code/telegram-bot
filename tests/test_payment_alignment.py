from decimal import Decimal

import pytest

from utils.payment_alignment import Settlement, align_payment


@pytest.mark.parametrize("mode, kwargs, expected", [
    ("down", {}, (179, "62650", "0", "0", "75")),
    ("up", {"adjustment_authorized": True}, (180, "63000", "0", "275", "0")),
    ("separate", {"separate_channel": True}, (179, "62650", "75", "0", "0")),
])
def test_alignment_preserves_obligation(mode, kwargs, expected):
    original = Decimal("62725.00")
    rate = Decimal("350.00")
    result = align_payment(original, original, rate, mode, **kwargs)
    hours, *amounts = expected
    assert result == Settlement(hours, *map(Decimal, amounts))
    assert result.hourly_amount == result.hours * rate
    assert original + result.adjustment == result.hourly_amount + result.separate_amount + result.debt


def test_partial_payment_retains_total_unpaid_balance():
    result = align_payment(Decimal("80000"), Decimal("30000"), Decimal("350"), "down")
    assert result == Settlement(85, Decimal("29750"), Decimal(0), Decimal(0), Decimal("50250"))


@pytest.mark.parametrize("requested, rate, mode", [
    ("62725", "350", "up"), ("62725", "350", "separate"), ("62726", "350", "down"),
    ("10", "0", "down"), ("0.001", "350", "down"), ("NaN", "350", "down"),
])
def test_rejects_unauthorized_or_invalid_settlement(requested, rate, mode):
    with pytest.raises(ValueError):
        align_payment(Decimal("62725"), Decimal(requested), Decimal(rate), mode)
