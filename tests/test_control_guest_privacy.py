"""Regression tests for the mystery guest session boundary."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from routes import control


@pytest.fixture
def guest_session(monkeypatch):
    guest = {"user_id": 123, "full_name": "Private Name", "position": " Тайный гость ",
             "is_admin": True, "permissions": {"control_access": True,
             "control_manage": True, "control_view_all": True}}
    pool = MagicMock()
    conn = pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow = AsyncMock(return_value=guest)
    monkeypatch.setattr(control.db, "get_pool", lambda app: pool)
    return guest


def req(path):
    return SimpleNamespace(path=path, app={}, headers={"Authorization": "Bearer " + "a"*64})


@pytest.mark.parametrize("path", [
    "/api/control/restaurants", "/api/control/templates", "/api/control/guests",
    "/api/control/tasks", "/api/control/analytics", "/api/control/checks/assign",
    "/api/control/tasks/photos", "/api/control/photos/1", "/api/control/documents",
    "/api/control/schedules", "/api/control/haccp",
])
def test_guest_session_denies_other_paths(guest_session, path):
    assert asyncio.run(control.control_user(req(path))) is None


@pytest.mark.parametrize("path", [
    "/api/control/me", "/api/control/checks", "/api/control/checks/complete",
    "/api/control/checks/photo",
])
def test_guest_session_allows_own_work_routes(guest_session, path):
    assert asyncio.run(control.control_user(req(path))) == guest_session


def test_guest_profile_does_not_disclose_name(guest_session):
    response = asyncio.run(control.me(req("/api/control/me")))
    payload = json.loads(response.text)
    assert payload["full_name"] == "Тайный гость"
    assert "Private Name" not in response.text
    assert "user_id" not in payload
    assert response.headers["Cache-Control"] == "no-store"
