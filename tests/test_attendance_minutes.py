import pytest

from utils.attendance_minutes import worked_minutes


@pytest.mark.parametrize(("shifts", "expected"), [
    (["09:00-22:04"], 784),
    (["09:00-22:04", "22:05-22:12"], 791),
    (["09:00-12:00", "11:00-13:00"], 240),
    (["09:00-12:00", "09:00-12:00"], 180),
    (["22:00-06:00"], 480),
    (["23:59-24:00"], 1),
    (["12:00-13:00", "09:00-10:00"], 120),
    ([], 0),
])
def test_exact_minutes(shifts, expected):
    assert worked_minutes(shifts) == expected


@pytest.mark.parametrize("value", ["25:00-26:00", "09:60-12:00", "09:00-24:01", "09:00-09:00", "invalid"])
def test_invalid_shift(value):
    with pytest.raises(ValueError):
        worked_minutes([value])
