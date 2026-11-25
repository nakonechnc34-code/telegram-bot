import pytest
from utils.attendance_rounding import round_daily_minutes, allocate_daily_minutes


@pytest.mark.parametrize("actual,expected", [
    (0, 0), (1, 0), (2, 0), (3, 5), (4, 5),
    (482, 480), (483, 485), (487, 485), (488, 490),
    (538, 540), (1439, 1440), (1440, 1440),
])
def test_five_minute_rounding(actual, expected):
    assert round_daily_minutes(actual) == expected


@pytest.mark.parametrize("actual", [-1, 1441, True, 1.5])
def test_invalid_minutes(actual):
    with pytest.raises(ValueError):
        round_daily_minutes(actual)


def test_allocation_rounds_only_once():
    raw = {"a": 242, "b": 242}
    assert allocate_daily_minutes(raw) == {"a": 243, "b": 242}
    assert raw == {"a": 242, "b": 242}
    assert sum(allocate_daily_minutes(raw).values()) == 485


def test_allocation_zero_and_order():
    assert allocate_daily_minutes({"a": 0}) == {"a": 0}
    assert allocate_daily_minutes({"b": 242, "a": 242}) == {"a": 243, "b": 242}


def test_allocation_rejects_impossible_day():
    with pytest.raises(ValueError):
        allocate_daily_minutes({"a": 800, "b": 800})


def test_no_rounding():
    assert allocate_daily_minutes({"a": 242, "b": 243}, 1) == {"a": 242, "b": 243}
