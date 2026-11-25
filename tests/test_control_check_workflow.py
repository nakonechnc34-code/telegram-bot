import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from routes import control


@pytest.fixture
def setup_check(monkeypatch):
    guest = {"user_id": 123, "position": "Тайный гость",
             "permissions": {"control_access": True}}
    monkeypatch.setattr(control, "control_user", AsyncMock(return_value=guest))
    pool = MagicMock()
    conn = pool.acquire.return_value.__aenter__.return_value
    conn.fetchrow = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()
    conn.transaction = MagicMock()
    monkeypatch.setattr(control.db, "get_pool", lambda app: pool)
    request = SimpleNamespace(app={}, json=AsyncMock(return_value={
        "id": 42, "answers": {"0:0": "no"}
    }))
    return conn, request


def test_guest_cannot_complete_foreign_check(setup_check):
    conn, request = setup_check
    conn.fetchrow.return_value = None
    assert asyncio.run(control.complete_check(request)).status == 404
    query, *args = conn.fetchrow.call_args.args
    assert "c.guest_id=$3" in query
    assert args == [42, [], 123]
    conn.execute.assert_not_called()


def test_completed_check_cannot_be_submitted_twice(setup_check):
    conn, request = setup_check
    conn.fetchrow.return_value = {"completed_at": "already completed"}
    assert asyncio.run(control.complete_check(request)).status == 409
    conn.execute.assert_not_called()


@pytest.mark.parametrize("photo_required", [False, True])
def test_guest_check_creates_corrective_task_only_with_required_evidence(setup_check, photo_required):
    conn, request = setup_check
    conn.fetchrow.return_value = {"id": 42, "completed_at": None, "definition": {
        "sections": [{"questions": [{"type": "yes_no_na", "weight": 1,
            "required": True, "critical": True, "text": "Clean equipment",
            "photo_required": photo_required}]}]
    }}
    response = asyncio.run(control.complete_check(request))
    if photo_required:
        assert response.status == 400
        conn.execute.assert_not_called()
        conn.fetch.return_value = [{"question_key": "0:0"}]
        response = asyncio.run(control.complete_check(request))
    assert response.status == 200
    assert json.loads(response.text) == {"score": 0, "violations": 1}
    assert conn.execute.await_count == 2
    assert "UPDATE control_checks" in conn.execute.call_args_list[0].args[0]
    assert conn.execute.call_args_list[1].args[1:] == (42, "0:0", "Clean equipment", True)
