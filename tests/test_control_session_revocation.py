from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from routes import control


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"is_fired": True},
    {"permissions": {"control_access": False}},
    {"position": "Повар"},
    {"position": "Тайный гость"},
])
async def test_existing_token_rechecks_current_access(monkeypatch, change):
    user = {"user_id": 42, "position": "УС", "permissions": {"control_access": True}}
    conn = AsyncMock()
    conn.fetchrow.side_effect = [user, {**user, **change}]
    pool = MagicMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    monkeypatch.setattr(control.db, "get_pool", lambda app: pool)
    request = SimpleNamespace(app={}, path="/api/control/restaurants",
                              headers={"Authorization": "Bearer " + "a"*64})
    assert await control.control_user(request) == user
    assert await control.control_user(request) is None
    assert conn.fetchrow.await_count == 2
    assert "s.expires_at>NOW()" in conn.fetchrow.call_args.args[0]


@pytest.mark.asyncio
async def test_deleted_or_expired_session(monkeypatch):
    conn = AsyncMock()
    conn.fetchrow.return_value = None
    pool = MagicMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    monkeypatch.setattr(control.db, "get_pool", lambda app: pool)
    request = SimpleNamespace(app={}, path="/api/control/me",
                              headers={"Authorization": "Bearer " + "a"*64})
    assert await control.control_user(request) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", [control.get_check_photo, control.get_task_photo])
@pytest.mark.parametrize("raw", ["0", "9223372036854775808", "9"*100, "１２"])
async def test_invalid_photo_id_never_reaches_database(monkeypatch, handler, raw):
    monkeypatch.setattr(control, "control_user", AsyncMock(return_value={"user_id": 42}))
    scope = AsyncMock()
    monkeypatch.setattr(control, "restaurant_scope", scope)
    response = await handler(SimpleNamespace(match_info={"id": raw}))
    assert response.status == 404
    scope.assert_not_awaited()
