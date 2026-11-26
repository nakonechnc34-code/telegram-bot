from unittest.mock import MagicMock, patch

from routes.timesheet import _sync_preview_attendance


def preview(rows, allowed=True, employees=None):
    conn = MagicMock()
    cursor = conn.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        employees if employees is not None else [{"user_id": 1, "personnel_number": "021", "restaurant_key": "a"}],
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
    assert result["records"][0]["personnel_number"] == "21"


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


def test_saved_attendance_conflicts():
    from routes.timesheet import _attendance_saved_conflict
    cursor = MagicMock()
    record = {"personnel_number": "021", "date": "2026-11-17",
              "restaurant_key": "a", "shifts": ["05:00-09:00"]}
    saved = {"restaurant_key": "b", "work_date": "2026-11-16",
             "status": "work", "start_minute": 1320, "end_minute": 1800}
    cursor.fetchall.return_value = [saved]
    assert _attendance_saved_conflict(cursor, [record], {"021": 1})
    cursor.fetchall.return_value = [dict(saved, end_minute=1740)]
    assert not _attendance_saved_conflict(cursor, [record], {"021": 1})
    cursor.fetchall.return_value = [dict(saved, restaurant_key="a",
        work_date="2026-11-17", start_minute=300, end_minute=540)]
    assert not _attendance_saved_conflict(cursor, [record], {"021": 1})
    cursor.fetchall.return_value = [dict(saved, work_date="2026-11-17",
        status="sick", start_minute=None, end_minute=None)]
    assert _attendance_saved_conflict(cursor, [record], {"021": 1})


def test_excel_to_preview_preserves_minutes_and_personnel_number():
    from datetime import date
    from io import BytesIO
    from openpyxl import Workbook
    from routes.timesheet import _parse_excel_rows

    wb = Workbook()
    ws = wb.active
    ws.append(["Отчёт посещаемости"])
    ws.append(["Табельный номер", "Ресторан", date(2026, 11, 16), date(2026, 11, 17)])
    ws.append(["021", "A", "09:05-12:20", "22:10-06:05"])
    ws.append([None, "A", "11:50-13:10", None])
    ws.append([None, "B", "14:00-14:35", None])
    buf = BytesIO()
    wb.save(buf)
    rows = _parse_excel_rows(buf.getvalue())
    assert len(rows) == 4
    assert all(row[1] == "021" for row in rows)
    result = preview(rows)
    assert result["ok"]
    assert result["total_minutes"] == 755
    assert sorted(record["minutes"] for record in result["records"]) == [35, 245, 475]

def test_preview_numeric_aliases_merge():
    result = preview([("2026-11-16", "21", "09:00-12:00", "A"),
                      ("2026-11-16", "0021", "11:00-13:00", "A")])
    assert result["ok"]
    assert result["total_minutes"] == 240
    assert len(result["records"]) == 1


def test_preview_ambiguous_numeric_aliases_rejected():
    result = preview([("2026-11-16", "021", "09:00-12:00", "A")],
                     employees=[{"user_id": 1, "personnel_number": "021", "restaurant_key": "a"},
                                {"user_id": 2, "personnel_number": "21", "restaurant_key": "a"}])
    assert not result["ok"]
    assert not result["records"]
    assert "021" in result["errors"][0]
    assert "неоднозначен" in result["errors"][0]


def test_matching_errors_are_grouped_by_employee_and_restaurant():
    result = preview([("2026-11-16", "9181", "10:03-21:59", "A"),
                      ("2026-11-17", "9181", "9:59-21:59", "A")])
    assert not result["ok"]
    assert result["error_count"] == 1
    assert "не найден" in result["errors"][0]


def test_restaurant_name_normalization():
    from routes.timesheet import _attendance_restaurant_name
    assert _attendance_restaurant_name("  Белая   дача ") == _attendance_restaurant_name("БЕЛАЯ ДАЧА")


def test_manual_mapping_permissions_and_validation():
    import pytest
    from routes.timesheet import _apply_attendance_mapping
    rows = [("2026-11-16", "9181", "09:00-12:00", "Белая дача")]
    mapping = {"employees": {"9181": "021"}, "restaurants": {"Белая дача": "A"}}
    with patch("routes.timesheet._is_hr_or_super", return_value=False):
        with pytest.raises(PermissionError):
            _apply_attendance_mapping({"user_id": 1}, rows, mapping)
    with patch("routes.timesheet._is_hr_or_super", return_value=True):
        mapped = _apply_attendance_mapping({"user_id": 1}, rows, mapping)
        assert mapped == [("2026-11-16", "021", "09:00-12:00", "A")]
        assert preview(mapped)["total_minutes"] == 180
        for invalid in [{"employees": {"missing": "021"}}, {"restaurants": {"Белая дача": 1}}, {"extra": {}}, {"employees": []}]:
            with pytest.raises(ValueError):
                _apply_attendance_mapping({"user_id": 1}, rows, invalid)


def test_manual_mapping_unknown_target_still_blocks_save():
    from routes.timesheet import _apply_attendance_mapping
    rows = [("2026-11-16", "9181", "09:00-12:00", "A")]
    with patch("routes.timesheet._is_hr_or_super", return_value=True):
        mapped = _apply_attendance_mapping({"user_id": 1}, rows, {"employees": {"9181": "999"}})
    assert not preview(mapped)["ok"]


def test_http_manual_mapping():
    import asyncio
    import json
    from aiohttp import web, FormData
    from aiohttp.test_utils import TestClient, TestServer
    from unittest.mock import AsyncMock
    from routes.timesheet import handle_import_attendance

    async def scenario():
        app = web.Application()
        for endpoint in ("preview", "stage"):
            app.router.add_post("/api/timesheet/import_attendance/" + endpoint, handle_import_attendance)
        rows = [("2026-11-16", "9181", "09:00-12:00", "A")]
        async def run(fn, *args):
            if fn.__name__ == "_parse_excel_rows":
                return rows
            if fn.__name__ == "_load_saved_attendance_mapping":
                return []
            assert args[1][0][1] == "021"
            return {"ok": True}
        async with TestClient(TestServer(app)) as client:
            for endpoint in ("preview", "stage"):
                for allowed, payload, expected in [
                    (False, {"employees": {"9181": "021"}}, 403),
                    (True, [], 400),
                    (True, None, 400),
                    (True, {"employees": {"absent": "021"}}, 400),
                    (True, {"employees": {"9181": "021"}}, 200),
                ]:
                    data = FormData()
                    data.add_field("file", b"fixture", filename="test.xlsx")
                    data.add_field("mapping", json.dumps(payload))
                    with patch("routes.timesheet._timesheet_user", new=AsyncMock(return_value=({"user_id": 1}, None))), \
                         patch("routes.timesheet._require_timesheet_access"), \
                         patch("routes.timesheet._is_hr_or_super", return_value=allowed), \
                         patch("routes.timesheet._is_tu", return_value=not allowed), \
                         patch("routes.timesheet._run", side_effect=run):
                        response = await client.post("/api/timesheet/import_attendance/" + endpoint, data=data)
                        assert response.status == expected
                        await response.read()
    asyncio.run(scenario())


def test_saved_mapping_is_single_pass_and_manual_override():
    from routes.timesheet import _merge_saved_attendance_mapping
    rows = [("2026-11-16", "9181", "09:00-12:00", "A")]
    saved = [
        {"kind": "employees", "source": "9181", "target": "021"},
        {"kind": "employees", "source": "021", "target": "999"},
        {"kind": "restaurants", "source": "A", "target": "B"},
    ]
    assert _merge_saved_attendance_mapping(rows, saved, None) == [
        ("2026-11-16", "021", "09:00-12:00", "B")]
    assert _merge_saved_attendance_mapping(rows, saved, {"employees": {"9181": "42"}}) == [
        ("2026-11-16", "42", "09:00-12:00", "B")]
