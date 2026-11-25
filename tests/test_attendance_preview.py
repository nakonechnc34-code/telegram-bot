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


def test_preview_absence_statuses():
    result = preview([
        ("2026-11-16", "021", "В", "A"),
        ("2026-11-17", "021", "Б", "A"),
        ("2026-11-18", "021", "Н", "A"),
    ])
    assert result["ok"]
    assert result["total_minutes"] == 0
    assert {r["status"] for r in result["records"]} == {"vacation", "sick", "absent"}


def test_preview_absence_work_conflict():
    result = preview([
        ("2026-11-16", "021", "В", "A"),
        ("2026-11-16", "021", "09:00-12:00", "B"),
    ])
    assert not result["ok"]
    assert result["total_minutes"] is None


def test_delete_attendance_denied_scope():
    from routes.timesheet import _sync_delete_attendance
    conn = MagicMock()
    cursor = conn.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"key": "b", "territory_manager_id": 2}
    with patch("routes.timesheet.get_conn", return_value=conn), \
         patch("routes.timesheet._restaurant_in_scope", return_value=False):
        assert _sync_delete_attendance({"user_id": 1}, 42, "b") is None
    assert all(call.args[0].startswith("SELECT") for call in cursor.execute.call_args_list)


def test_delete_attendance_scoped_and_repeat():
    from routes.timesheet import _sync_delete_attendance
    conn = MagicMock()
    cursor = conn.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"key": "a", "territory_manager_id": 1}
    with patch("routes.timesheet.get_conn", return_value=conn), \
         patch("routes.timesheet._restaurant_in_scope", return_value=True):
        for count in (3, 0):
            cursor.rowcount = count
            assert _sync_delete_attendance({"user_id": 1}, 42, "a") == count
    deletes = [call.args for call in cursor.execute.call_args_list if call.args[0].startswith("DELETE")]
    assert len(deletes) == 4
    for sql, params in deletes[::2]:
        assert "import_id = %s AND restaurant_key = %s" in sql
        assert params == (42, "a")
    for sql, params in deletes[1::2]:
        assert "NOT EXISTS" in sql
        assert params == (42,)
    assert all("timesheet_records" not in sql for sql, _ in deletes)
