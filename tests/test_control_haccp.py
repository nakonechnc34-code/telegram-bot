import pytest
from routes.control import reading_number, reading_deviation

@pytest.mark.parametrize("value", [True, None, "", "NaN", "Infinity", "1e999", "0.00001"])
def test_invalid(value):
    with pytest.raises(ValueError):
        reading_number(value)

def test_bounds():
    lo, hi = reading_number("2"), reading_number("6")
    assert not reading_deviation(lo, lo, hi)
    assert not reading_deviation(hi, lo, hi)
    assert reading_deviation(reading_number("6.1"), lo, hi)
    assert reading_deviation(reading_number("1.9"), lo, hi)
