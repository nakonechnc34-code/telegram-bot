"""Регрессии контроля доступа, входа, сессий и валидации табеля."""
import asyncio
import json
from ipaddress import ip_network
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from multidict import CIMultiDict

from middleware import rate_limit
from routes import auth, medbooks, timesheet, users
from utils import auth_helpers


def request(body=None, headers=(), remote="192.0.2.10"):
    return SimpleNamespace(
        json=AsyncMock(return_value=body),
        read=AsyncMock(return_value=json.dumps(body).encode()),
        headers=CIMultiDict(headers),
        query={},
        remote=remote,
        method="POST",
        path="/api/test",
    )


@pytest.mark.parametrize("handler", [auth.handle_auth_login_staff, auth.handle_auth_login_admin])
def test_login_uses_transport_ip(handler, monkeypatch):
    monkeypatch.setattr(rate_limit.config, "TRUSTED_PROXY_NETWORKS", ())
    limit = Mock(return_value=False)
    monkeypatch.setattr(auth, "_check_rate_limit", limit)
    req = request({"login": "abc01", "password": "secret"},
                  [("X-Forwarded-For", "198.51.100.1"), ("X-Real-IP", "198.51.100.2")])
    assert asyncio.run(handler(req)).status == 429
    limit.assert_called_once_with("192.0.2.10")


@pytest.mark.parametrize(("headers", "expected"), [
    ([("X-Forwarded-For", "198.51.100.1, 203.0.113.8")], "203.0.113.8"),
    ([("X-Forwarded-For", "198.51.100.1, invalid")], "192.0.2.10"),
    ([("X-Forwarded-For", "198.51.100.1"), ("X-Forwarded-For", "203.0.113.8")], "192.0.2.10"),
])
def test_trusted_proxy_uses_valid_address_from_right(monkeypatch, headers, expected):
    monkeypatch.setattr(rate_limit.config, "TRUSTED_PROXY_NETWORKS", (ip_network("192.0.2.0/24"),))
    assert rate_limit.get_client_ip(request(headers=headers)) == expected


@pytest.mark.parametrize("handler", [medbooks.handle_admin_medbooks, medbooks.handle_admin_medbook_get,
                                     medbooks.handle_admin_medbook_save])
def test_medbooks_require_role_or_permission(handler, monkeypatch):
    admin = {"user_id": 42, "is_admin": True, "permissions": {"users_edit": True}}
    monkeypatch.setattr(medbooks, "get_admin_user", AsyncMock(return_value=(admin, None)))
    run = AsyncMock()
    monkeypatch.setattr(medbooks, "_run", run)
    assert asyncio.run(handler(request({"user_id": 123}))).status == 403
    run.assert_not_called()


@pytest.mark.parametrize("handler", [medbooks.handle_admin_medbook_get, medbooks.handle_admin_medbook_save])
def test_territorial_manager_medbook_operations_scope_the_database_query(handler, monkeypatch):
    admin = {"user_id": 42, "position": "Территориальный управляющий",
             "permissions": {"medbook_edit": True}}
    monkeypatch.setattr(medbooks, "get_admin_user", AsyncMock(return_value=(admin, None)))
    cursor = mock_cursor(medbooks, monkeypatch)
    cursor.fetchone.return_value = None
    cursor.rowcount = 0
    assert asyncio.run(handler(request({"user_id": 123}))).status == 404
    query, params = cursor.execute.call_args.args
    assert "territory_manager_id = %s" in query
    assert params[-2:] == (123, 42)


def test_employee_list_omits_medbook_for_admin_without_access(monkeypatch):
    monkeypatch.setattr(users, "get_admin_user", AsyncMock(return_value=({"is_admin": True}, None)))
    records = [{"user_id": 123, "medbook": {"doctors": {"1": "01.01.2026"}}}]
    run = AsyncMock(return_value=records)
    monkeypatch.setattr(users, "_run", run)
    employee, = json.loads(asyncio.run(users.handle_admin_users(request({}))).text)["users"]
    assert "medbook" not in employee
    assert employee["medbook_status"] == "—"
    run.assert_awaited_once()


def mock_cursor(module, monkeypatch):
    async def run(fn, *args):
        return fn(*args)

    monkeypatch.setattr(module, "_run", run)
    connection = MagicMock()
    monkeypatch.setattr(module, "get_conn", connection)
    return connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value


@pytest.mark.parametrize(("headers", "body"), [
    ([("Authorization", "Bearer session")], {}),
    ([("Content-Type", "application/json")], {"webToken": "session"}),
])
def test_logout_revokes_header_and_legacy_body_sessions(monkeypatch, headers, body):
    run = AsyncMock()
    monkeypatch.setattr(auth, "_run", run)
    assert asyncio.run(auth.handle_auth_logout(request(body, headers))).status == 200
    run.assert_awaited_once_with(auth._sync_delete_session, "session")


def test_session_lookup_checks_database_after_revocation(monkeypatch):
    cursor = mock_cursor(auth_helpers, monkeypatch)
    cursor.fetchone.side_effect = [(123,), None]
    assert auth_helpers._sync_get_session_user("session") == 123
    assert auth_helpers._sync_get_session_user("session") is None
    assert cursor.execute.call_count == 2
    query, params = cursor.execute.call_args.args
    assert "last_used_at > NOW()" in query
    assert params == ("session", auth_helpers.SESSION_TTL_DAYS)


@pytest.mark.parametrize("bad_fields", [
    {"user_id": True}, {"user_id": 1.2}, {"work_date": "2026-02-30"},
    {"hours": "garbage"}, {"hours": "NaN"}, {"hours": float("inf")},
    {"hours": -1}, {"hours": 24.1}, {"status": "other"}, {"start_time": "24:01"},
    {"end_time": "15:60"}, {"restaurant_key": ["unit-a"]},
])
def test_save_cell_rejects_invalid_values_before_database(monkeypatch, bad_fields):
    employee = {"user_id": 123, "is_super_admin": True}
    monkeypatch.setattr(timesheet, "_timesheet_user", AsyncMock(return_value=(employee, None)))
    run = AsyncMock()
    monkeypatch.setattr(timesheet, "_run", run)
    body = {"user_id": 123, "work_date": "2026-11-20", "hours": 8, **bad_fields}
    assert asyncio.run(timesheet.handle_timesheet_save_cell(request(body))).status == 400
    run.assert_not_called()


def test_save_cell_preserves_zero_hour_removal_and_overnight_shifts(monkeypatch):
    employee = {"user_id": 123, "is_super_admin": True}
    monkeypatch.setattr(timesheet, "_timesheet_user", AsyncMock(return_value=(employee, None)))
    cursor = mock_cursor(timesheet, monkeypatch)
    cursor.description = [("user_id",), ("is_super_admin",)]
    cursor.fetchone.side_effect = [None, (123, True), None, (123, True)]
    body = {"user_id": "123", "work_date": "2026-11-20", "hours": 0}
    assert asyncio.run(timesheet.handle_timesheet_save_cell(request(body))).status == 200
    assert cursor.execute.call_args.args[0].startswith("DELETE")
    body.update(hours="8,5", start_time="22:30", end_time="07:00")
    assert asyncio.run(timesheet.handle_timesheet_save_cell(request(body))).status == 200
    query, params = cursor.execute.call_args.args
    assert query.startswith("INSERT")
    assert params[2] == 8.5
    assert str(params[-2]) == "22:30:00" and str(params[-1]) == "07:00:00"


def test_attendance_import_only_writes_valid_rows_in_scope(monkeypatch):
    employee = {"user_id": 123, "restaurant_key": "a"}
    cursor = mock_cursor(timesheet, monkeypatch)
    cursor.fetchall.side_effect = [
        [{"user_id": 123, "personnel_number": "123", "restaurant_key": "a"},
         {"user_id": 456, "personnel_number": "456", "restaurant_key": "b"}],
        [{"key": "a", "name": "A", "territory_manager_id": None},
         {"key": "b", "name": "B", "territory_manager_id": None}],
    ]
    rows = [("2026-11-20", "123", "NaN"), ("2026-11-20", "123", "24:99-02:00"),
            ("2026-11-20", "456", "8"), ("2026-11-20", "123", "8", "B"),
            ("2026-11-20", "123", "22:00-06:00")]
    count, errors = timesheet._sync_import_attendance(employee, rows)
    assert (count, len(errors)) == (1, 4)
    assert cursor.execute.call_count == 3
    assert cursor.execute.call_args.args[1][:5] == (123, "2026-11-20", 8, "work", "a")


def test_hr_position_requires_admin_role():
    user = {"position": " HR ", "is_admin": False}
    assert not auth_helpers._is_hr_or_super(user)
    assert not auth_helpers._sync_user_has_perm(user, "timesheet_access")


def test_delegated_admin_cannot_assign_hr(monkeypatch):
    admin = {"user_id": 42, "is_admin": True, "is_super_admin": False,
             "permissions": {"users_edit": True}}
    monkeypatch.setattr(users, "get_admin_user", AsyncMock(return_value=(admin, None)))
    monkeypatch.setattr(users, "_check_admin_can_manage_user", AsyncMock(return_value=True))
    run = AsyncMock(return_value={"user_id": 123, "position": "Работник"})
    monkeypatch.setattr(users, "_run", run)
    response = asyncio.run(users.handle_admin_user_update(request({
        "user_id": 123, "updates": {"position": " hr "}
    })))
    assert response.status == 403
    run.assert_awaited_once_with(users._sync_get_user_by_id, 123)


@pytest.mark.parametrize("handler_name", ["handle_academy_course_detail", "handle_academy_submit_test"])
def test_employee_academy_routes_only_access_published_courses(handler_name, monkeypatch):
    from routes import academy

    monkeypatch.setattr(academy, "get_auth_user", AsyncMock(return_value=({"user_id": 42}, None)))
    cursor = mock_cursor(academy, monkeypatch)
    cursor.fetchone.return_value = None
    response = asyncio.run(getattr(academy, handler_name)(request({"course_id": 10})))
    assert response.status == 404
    cursor.execute.assert_called_once()
    query, params = cursor.execute.call_args.args
    assert "COALESCE(is_published, TRUE)" in query
    assert params == (10,)


def test_api_limiter_uses_same_ip_policy_as_login(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "true")
    monkeypatch.setattr(rate_limit.config, "TRUSTED_PROXY_NETWORKS", ())
    check = Mock(return_value=False)
    monkeypatch.setattr(rate_limit, "_check_rate", check)
    req = request(headers=[("X-Forwarded-For", "198.51.100.1")])
    handler = AsyncMock()
    assert asyncio.run(rate_limit.api_rate_middleware(req, handler)).status == 429
    assert check.call_args.args[0] == req.remote
    handler.assert_not_called()


def test_timesheet_rejects_foreign_session(monkeypatch):
    monkeypatch.setattr(timesheet, "_extract_token", AsyncMock(return_value="foreign-token"))
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(timesheet, "_run", lookup)
    assert asyncio.run(timesheet._timesheet_user(request({}))) == (None, 401)
    lookup.assert_awaited_once_with(timesheet._sync_timesheet_session, "foreign-token")


def test_timesheet_revoked_permission(monkeypatch):
    monkeypatch.setattr(timesheet, "_extract_token", AsyncMock(return_value="timesheet-token"))
    monkeypatch.setattr(timesheet, "_run", AsyncMock(return_value={"user_id": 123, "permissions": {}}))
    assert asyncio.run(timesheet._timesheet_user(request({}))) == (None, 403)


def test_timesheet_valid_session(monkeypatch):
    employee = {"user_id": 123, "permissions": {"timesheet_access": True}}
    monkeypatch.setattr(timesheet, "_extract_token", AsyncMock(return_value="timesheet-token"))
    monkeypatch.setattr(timesheet, "_run", AsyncMock(return_value=employee))
    assert asyncio.run(timesheet._timesheet_user(request({}))) == (employee, None)


def test_imported_day_blocks_manual_write(monkeypatch):
    employee = {"user_id": 123, "is_super_admin": True}
    monkeypatch.setattr(timesheet, "_timesheet_user", AsyncMock(return_value=(employee, None)))
    cursor = mock_cursor(timesheet, monkeypatch)
    cursor.fetchone.return_value = (1,)
    body = {"user_id": 123, "work_date": "2026-11-20", "hours": 8}
    assert asyncio.run(timesheet.handle_timesheet_save_cell(request(body))).status == 409
    assert all(call.args[0].startswith("SELECT") for call in cursor.execute.call_args_list)


def test_legacy_import_endpoint_disabled(monkeypatch):
    employee = {"user_id": 123, "is_super_admin": True}
    monkeypatch.setattr(timesheet, "_timesheet_user", AsyncMock(return_value=(employee, None)))
    req = request()
    req.path = "/api/timesheet/import_attendance"
    assert asyncio.run(timesheet.handle_import_attendance(req)).status == 410


def test_shared_timesheet_export_requires_permission(monkeypatch):
    employee = {"user_id": 123}
    monkeypatch.setattr(timesheet, "_timesheet_user", AsyncMock(return_value=(employee, None)))
    monkeypatch.setattr(timesheet, "_sync_user_has_perm", Mock(return_value=False))
    from aiohttp import web
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(timesheet.handle_timesheet_export_excel(request()))


def test_personal_export_escapes_formula(monkeypatch):
    import io
    from openpyxl import load_workbook
    employee = {"user_id": 123}
    monkeypatch.setattr(timesheet, "_timesheet_user", AsyncMock(return_value=(employee, None)))
    run = AsyncMock(return_value=[{"full_name": "=1+1", "position": "Cook",
        "restaurant_name": "A", "total_hours": 8.5, "rate": 350, "total_salary": 2975}])
    monkeypatch.setattr(timesheet, "_run", run)
    req = request()
    req.query = {"only_me": "true", "date_from": "2026-11-01", "date_to": "2026-11-30"}
    response = asyncio.run(timesheet.handle_timesheet_export_excel(req))
    assert response.status == 200
    run.assert_awaited_once_with(timesheet._sync_reports, 123, "2026-11-01", "2026-11-30", True)
    sheet = load_workbook(io.BytesIO(response.body)).active
    assert sheet["A2"].value == "=1+1" and sheet["A2"].data_type == "s"
    assert sheet["F2"].value == 2975


@pytest.mark.parametrize("hours,destination", [(0, None), (8, None), (8, "a")])
def test_save_cell_rejects_existing_foreign_restaurant(monkeypatch, hours, destination):
    cursor = mock_cursor(timesheet, monkeypatch)
    cursor.description = [("user_id",), ("position",), ("restaurant_key",)]
    cursor.fetchone.side_effect = [None, (42, "Управляющий сменой", "a"), ("a",), ("b",)]
    assert timesheet._sync_save_cell(42, 123, "2026-11-20", hours, "work", destination) == "forbidden"
    assert not any(call.args[0].lstrip().startswith(("DELETE", "INSERT", "UPDATE")) for call in cursor.execute.call_args_list)


def test_save_cell_allows_existing_local_restaurant(monkeypatch):
    cursor = mock_cursor(timesheet, monkeypatch)
    cursor.description = [("user_id",), ("position",), ("restaurant_key",)]
    cursor.fetchone.side_effect = [None, (42, "Управляющий сменой", "a"), ("a",), ("a",)]
    assert timesheet._sync_save_cell(42, 123, "2026-11-20", 8, "work", "a") is True
    assert cursor.execute.call_args.args[0].startswith("INSERT")


@pytest.mark.parametrize("position,admin,super_admin,territory,existing,expected", [
    ("HR", True, False, [], "b", True),
    ("", True, True, [], "b", True),
    ("Территориальный управляющий", False, False, [("a",), ("b",)], "b", True),
    ("Территориальный управляющий", False, False, [("a",)], "b", "forbidden"),
])
def test_save_cell_role_scope(monkeypatch, position, admin, super_admin, territory, existing, expected):
    cursor = mock_cursor(timesheet, monkeypatch)
    cursor.description = [(k,) for k in ("user_id", "position", "restaurant_key", "is_admin", "is_super_admin")]
    cursor.fetchone.side_effect = [None, (42, position, "a", admin, super_admin), ("a",), (existing,)]
    cursor.fetchall.return_value = territory
    assert timesheet._sync_save_cell(42, 123, "2026-11-20", 8, "work", "a") == expected
    writes = [call for call in cursor.execute.call_args_list if call.args[0].lstrip().startswith(("INSERT", "DELETE", "UPDATE"))]
    assert bool(writes) == (expected is True)


def test_ordinary_employee_cannot_write_timesheet_without_permission(monkeypatch):
    from aiohttp import web
    employee = {"user_id": 123, "position": "Повар", "restaurant_key": "a"}
    monkeypatch.setattr(timesheet, "_timesheet_user", AsyncMock(return_value=(employee, None)))
    monkeypatch.setattr(timesheet, "_sync_user_has_perm", Mock(return_value=False))
    run = AsyncMock()
    monkeypatch.setattr(timesheet, "_run", run)
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(timesheet.handle_timesheet_save_cell(request({"user_id": 123, "work_date": "2026-11-20", "hours": 8})))
    run.assert_not_awaited()


def test_save_cell_returns_403_on_transaction_scope_denial(monkeypatch):
    employee = {"user_id": 42, "position": "Управляющий сменой", "restaurant_key": "a"}
    monkeypatch.setattr(timesheet, "_timesheet_user", AsyncMock(return_value=(employee, None)))
    monkeypatch.setattr(timesheet, "_sync_user_has_perm", Mock(return_value=True))
    run = AsyncMock(side_effect=[True, "forbidden"])
    monkeypatch.setattr(timesheet, "_run", run)
    response = asyncio.run(timesheet.handle_timesheet_save_cell(request({"user_id": 123, "work_date": "2026-11-20", "hours": 0})))
    assert response.status == 403
    assert json.loads(response.body)["error"] == "forbidden_restaurant"


@pytest.mark.parametrize("position,admin,super_admin,expected_sql,params", [
    ("HR", True, False, "ORDER BY name", ()),
    ("", True, True, "ORDER BY name", ()),
    ("Территориальный управляющий", False, False, "WHERE territory_manager_id = %s", (42,)),
    ("Управляющий сменой", False, False, "WHERE key = %s", ("a",)),
    ("Повар", False, False, "WHERE key = %s", ("a",)),
])
def test_timesheet_restaurant_directory_scope(monkeypatch, position, admin, super_admin, expected_sql, params):
    user = {"user_id": 42, "position": position, "is_admin": admin,
            "is_super_admin": super_admin, "restaurant_key": "a"}
    monkeypatch.setattr(timesheet, "_timesheet_user", AsyncMock(return_value=(user, None)))
    monkeypatch.setattr(timesheet, "_sync_user_has_perm", Mock(return_value=True))
    cursor = mock_cursor(timesheet, monkeypatch)
    cursor.fetchall.return_value = [{"key": "a", "name": "A"}]
    response = asyncio.run(timesheet.handle_timesheet_restaurants(request()))
    assert response.status == 200
    args = cursor.execute.call_args.args
    assert expected_sql in args[0]
    assert (args[1] if len(args) > 1 else ()) == params
    if not params:
        assert "WHERE" not in args[0]
    assert json.loads(response.body)["restaurants"] == [{"key": "a", "name": "A"}]


def test_timesheet_restaurant_directory_requires_permission(monkeypatch):
    from aiohttp import web
    monkeypatch.setattr(timesheet, "_timesheet_user", AsyncMock(return_value=({"user_id": 42}, None)))
    monkeypatch.setattr(timesheet, "_sync_user_has_perm", Mock(return_value=False))
    run = AsyncMock()
    monkeypatch.setattr(timesheet, "_run", run)
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(timesheet.handle_timesheet_restaurants(request()))
    run.assert_not_awaited()
