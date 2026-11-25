from unittest.mock import MagicMock, patch

from routes.timesheet import _sync_preview_attendance


def preview(rows, allowed=True):
    conn = MagicMock()
    cursor = conn.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [{"user_id": 1, "personnel_number": "021", "restaurant_key": "a"}],
        [{"key": "a", "name": "A", "territory_manager_id": 1},
         {"key": "b", "name": "B", "territory_manager_id": 2}],
    ]
    with patch("routes.timesheet.get_conn", return_value=conn), \
         patch("routes.timesheet._restaurant_in_scope", return_value=allowed):
        result = _sync_preview_attendance({"user_id": 1}, rows)
    assert cursor.execute.call_count == 2
    assert all(call.args[0].strip().startswith("SELECT") for call in cursor.execute.call_args_list)
    return result


def test_preview_multiple_shifts():
    result = preview([
        ("2026-11-16", "021", "09:00-12:00", "A"),
        ("2026-11-16", "021", "11:00-13:00", "A"),
        ("2026-11-16", "021", "14:00-15:00", "B"),
    ])
    assert result["ok"]
    assert result["total_minutes"] == 300
    assert len(result["records"]) == 2
    assert result["records"][0]["personnel_number"] == "021"


def test_preview_cross_restaurant_overlap():
    result = preview([
        ("2026-11-16", "021", "09:00-12:00", "A"),
        ("2026-11-16", "021", "11:00-13:00", "B"),
    ])
    assert not result["ok"]
    assert result["total_minutes"] is None


def test_preview_denied_restaurant():
    result = preview([("2026-11-16", "021", "09:00-12:00", "A")], allowed=False)
    assert not result["ok"]
    assert not result["records"]


def test_preview_unknown_restaurant():
    result = preview([("2026-11-16", "021", "09:00-12:00", "Unknown")])
    assert not result["ok"]
    assert not result["records"]


def test_preview_night_shift():
    result = preview([("2026-11-16", "021", "22:00-06:00", "A")])
    assert result["ok"]
    assert result["total_minutes"] == 480


def test_preview_overlap_next_day():
    result = preview([
        ("2026-11-16", "021", "22:00-06:00", "A"),
        ("2026-11-17", "021", "05:00-09:00", "A"),
    ])
    assert not result["ok"]
    assert result["total_minutes"] is None


def test_preview_adjacent_night_shifts():
    result = preview([
        ("2026-11-16", "021", "22:00-06:00", "A"),
        ("2026-11-17", "021", "06:00-09:00", "B"),
    ])
    assert result["ok"]
    assert result["total_minutes"] == 660
