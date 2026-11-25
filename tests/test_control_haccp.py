import pytest
from routes.control import reading_number, reading_deviation

@pytest.mark.parametrize("value", [True, None, "", "NaN", "Infinity", "1e999", "0.00001"])
def test_invalid(value):
    with pytest.raises(ValueError):
        reading_number(value)

def test_bounds():
    lo, hi = reading_number("2"), reading_number("6")
    assert not reading_deviation(lo, lo, hi)
    assert not reading_deviation(hi, lo, hi)
    assert reading_deviation(reading_number("6.1"), lo, hi)
    assert reading_deviation(reading_number("1.9"), lo, hi)


import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from routes import control

@pytest.mark.parametrize("value,comment,exists,status,deviation", [
    ("4", "", True, 201, False),
    ("7", "", True, 400, True),
    ("7", "  ", True, 400, True),
    ("7", "Проверить холодильник", True, 201, True),
    ("4", "", False, 404, False),
])
def test_reading_scope_and_deviation(monkeypatch, value, comment, exists, status, deviation):
    user = {"user_id": 12, "position": "УС", "restaurant_key": "a",
            "permissions": {"control_access": True}}
    monkeypatch.setattr(control, "control_user", AsyncMock(return_value=user))
    pool = MagicMock()
    conn = pool.acquire.return_value.__aenter__.return_value
    conn.transaction = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"lower_limit": reading_number("2"),
                                           "upper_limit": reading_number("6")} if exists else None)
    conn.fetchval = AsyncMock(return_value=99)
    monkeypatch.setattr(control.db, "get_pool", lambda app: pool)
    request = SimpleNamespace(app={}, json=AsyncMock(return_value={
        "equipment_id": 7, "value": value, "comment": comment}))
    response = asyncio.run(control.haccp_add_reading(request))
    assert response.status == status
    assert conn.fetchrow.call_args.args[1:] == (7, ["a"])
    if status == 201:
        assert json.loads(response.text)["deviation"] is deviation
        assert conn.fetchval.call_args.args[3:6] == (reading_number("2"), reading_number("6"), deviation)
    else:
        conn.fetchval.assert_not_called()
