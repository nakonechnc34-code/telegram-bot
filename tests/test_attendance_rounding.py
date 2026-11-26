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


@pytest.mark.parametrize("step", [1, 5, 10, 15, 30, 60])
def test_rounding_all_daily_values(step):
    for minutes in range(1441):
        expected = ((2 * minutes + step) // (2 * step)) * step
        assert round_daily_minutes(minutes, step) == expected


@pytest.mark.parametrize("step", [1, 5, 10, 15, 30, 60])
@pytest.mark.parametrize("raw", [
    {"a": 242, "b": 242}, {"a": 0, "b": 1},
    {"a": 720, "b": 720}, {"a": 0, "b": 0},
    {"a": 17, "b": 31, "c": 12},
])
def test_allocation_preserves_rounded_total(step, raw):
    allocated = allocate_daily_minutes(raw, step)
    assert sum(allocated.values()) == round_daily_minutes(sum(raw.values()), step)
    assert allocated == allocate_daily_minutes(dict(reversed(list(raw.items()))), step)
    assert all(value >= 0 for value in allocated.values())
    assert all(allocated[key] == 0 for key in raw if raw[key] == 0)
