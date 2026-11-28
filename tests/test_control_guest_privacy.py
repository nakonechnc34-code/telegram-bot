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

@pytest.mark.parametrize(("role","visible"), [
 ({"is_super_admin":True},True),
 ({"position":"HR","is_admin":True},True),
 ({"position":"Администратор","is_admin":True},False),
 ({"position":"Территориальный управляющий"},False),
 ({"position":"УС"},False),
])
def test_guest_directory_identity_by_role(monkeypatch,role,visible):
    actor={"user_id":42,"permissions":{"control_access":True,"control_manage":True},**role}
    monkeypatch.setattr(control,"control_user",AsyncMock(return_value=actor))
    monkeypatch.setenv("CONTROL_GUEST_ALIAS_SECRET","test-only-secret")
    pool=MagicMock()
    conn=pool.acquire.return_value.__aenter__.return_value
    conn.fetch=AsyncMock(return_value=[{"user_id":123456789,"full_name":"Private Name","position":"Тайный гость","permissions":{"control_access":True}}])
    monkeypatch.setattr(control.db,"get_pool",lambda app:pool)
    response=asyncio.run(control.list_guests(req("/api/control/guests")))
    assert response.status==200
    item=json.loads(response.text)["guests"][0]
    if visible:
        assert item=={"id":"123456789","name":"Private Name"}
    else:
        assert item["id"]==control.guest_alias(123456789)
        assert item["name"]=="Тайный гость "+item["id"][:10]
        assert "Private Name" not in response.text
        assert item["id"]!="123456789"
    assert response.headers["Cache-Control"]=="no-store"
