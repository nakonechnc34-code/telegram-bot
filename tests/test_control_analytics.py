from datetime import date
import pytest
from routes.control import analytics_period

def test_inclusive_period():
    assert analytics_period({"start":"2026-11-01","end":"2026-11-25"}) == (date(2026,11,1),date(2026,11,26))

@pytest.mark.parametrize("body",[{"start":"2026-11-02","end":"2026-11-01"},{"start":"2025-01-01","end":"2026-11-01"},{"start":"invalid","end":"2026-11-01"}])
def test_invalid_period(body):
    with pytest.raises(ValueError):
        analytics_period(body)


import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from routes import control

def test_analytics_weighted_scores_and_missing_data(monkeypatch):
    user = {"user_id": 1, "is_super_admin": True}
    monkeypatch.setattr(control, "control_user", AsyncMock(return_value=user))
    pool = MagicMock()
    conn = pool.acquire.return_value.__aenter__.return_value
    def row(key, scored, total):
        return {"restaurant_key": key, "name": key, "territory_manager_id": None,
                "territory_manager": None, "completed": scored, "scored": scored,
                "score_sum": total, "tasks_created": 0, "critical_tasks": 0, "overdue_now": 0}
    conn.fetch = AsyncMock(return_value=[row("a", 1, 100), row("b", 3, 150), row("c", 0, None)])
    monkeypatch.setattr(control.db, "get_pool", lambda app: pool)
    request = SimpleNamespace(app={}, json=AsyncMock(return_value={"start":"2026-11-01","end":"2026-11-25"}))
    response = asyncio.run(control.control_analytics(request))
    payload = json.loads(response.text)
    assert payload["summary"]["average_score"] == 62.5
    assert payload["territories"][0]["average_score"] == 62.5
    assert [r["average_score"] for r in payload["restaurants"]] == [100, 50, None]
    assert conn.fetch.call_args.args[1:] == (date(2026,11,1), date(2026,11,26), None)

@pytest.mark.parametrize("handler", [control.control_analytics, control.analytics_trends])
def test_us_cannot_filter_foreign_restaurant(monkeypatch, handler):
    user = {"user_id": 12, "position": "УС", "restaurant_key": "a",
            "permissions": {"control_access": True}}
    monkeypatch.setattr(control, "control_user", AsyncMock(return_value=user))
    pool = MagicMock()
    monkeypatch.setattr(control.db, "get_pool", pool)
    request = SimpleNamespace(app={}, json=AsyncMock(return_value={
        "start":"2026-11-01","end":"2026-11-25","restaurant_key":"b"}))
    assert asyncio.run(handler(request)).status == 404
    pool.assert_not_called()
