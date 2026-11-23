"""Regression tests for the employee payroll widget API."""
import asyncio
import json
from unittest.mock import AsyncMock, patch

from routes import timesheet


class Request:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def call(payload, *, authenticated=True, summary=None):
    user = {"user_id": 42} if authenticated else None
    err = None if authenticated else "unauthorized"
    with patch.object(timesheet, "get_auth_user", new_callable=AsyncMock, return_value=(user, err)), \
         patch.object(timesheet, "_run", new_callable=AsyncMock, return_value=summary) as run:
        response = asyncio.run(timesheet.handle_employee_payment_summary(Request(payload)))
        return response, run


def test_employee_summary_ignores_forged_user_id():
    data = {"total_hours": 12.0, "timesheet_accrued": 2400.0,
            "extra_accrued": 200.0, "paid": 500.0, "remaining": 2100.0}
    response, run = call({"user_id": 999, "date_from": "2026-11-01",
                          "date_to": "2026-11-30"}, summary=data)
    assert response.status == 200
    assert json.loads(response.body) == data
    run.assert_awaited_once_with(
        timesheet._sync_employee_payment_summary, 42, "2026-11-01", "2026-11-30"
    )


def test_invalid_date_range_rejected_without_query():
    response, run = call({"date_from": "2026-12-01", "date_to": "2026-11-01"})
    assert response.status == 400
    run.assert_not_awaited()


def test_invalid_body_rejected_without_query():
    response, run = call(["not a dict"])
    assert response.status == 400
    run.assert_not_awaited()


def test_missing_employee_returns_not_found():
    response, run = call({"date_from": "2026-11-01", "date_to": "2026-11-30"})
    assert response.status == 404
    run.assert_awaited_once()


def test_summary_query_scopes_timesheet_and_payments_to_authenticated_user():
    import inspect
    source = inspect.getsource(timesheet._sync_employee_payment_summary)
    assert "WHERE user_id = u.user_id" in source
    assert "WHERE u.user_id = %s" in source
    assert "status = 'approved'" in source
    assert "record_type = 'accrual'" in source
    assert "record_type = 'payout'" in source
    assert "BETWEEN %s::date AND %s::date" in source


def test_employee_endpoint_requires_authentication():
    # Unauthenticated requests must be denied before any database work.
    with patch.object(timesheet, "get_auth_user", new_callable=AsyncMock,
                      return_value=(None, {"error": "unauthorized"})), \
         patch.object(timesheet, "denied", return_value=timesheet.web.json_response(
             {"error": "unauthorized"}, status=401)), \
         patch.object(timesheet, "_run", new_callable=AsyncMock) as run:
        response = asyncio.run(timesheet.handle_employee_payment_summary(Request({})))
        assert response.status == 401
        run.assert_not_awaited()
