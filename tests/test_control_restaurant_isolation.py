import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from routes import control


@pytest.mark.parametrize("role,expected", [
    ({"position":"УС","permissions":{"control_access":True,"control_view_all":True}}, ["a"]),
    ({"position":"Территориальный управляющий"}, ["a","b"]),
    ({"position":"Администратор","is_admin":True}, ["a"]),
    ({"permissions":{"control_access":True,"control_view_all":True}}, ["a","b"]),
    ({"position":"УС","restaurant_key":None}, []),
])
def test_restaurant_directory_scope(monkeypatch, role, expected):
    user={"user_id":42,"restaurant_key":"a","permissions":{"control_access":True},**role}
    monkeypatch.setattr(control,"control_user",AsyncMock(return_value=user))
    conn=AsyncMock()
    conn.fetch.return_value=[{"key":"a","name":"A"},{"key":"b","name":"B"}]
    pool=MagicMock()
    pool.acquire.return_value.__aenter__.return_value=conn
    monkeypatch.setattr(control.db,"get_pool",lambda app:pool)
    response=asyncio.run(control.restaurants(SimpleNamespace(app={})))
    assert response.status==200
    assert [r["key"] for r in json.loads(response.text)["restaurants"]]==expected


def test_restaurant_reassignment_updates_scope():
    user={"position":"УС","restaurant_key":"a","permissions":{"control_access":True}}
    assert asyncio.run(control.restaurant_scope(user))==["a"]
    assert asyncio.run(control.restaurant_scope(dict(user,restaurant_key="b")))==["b"]
