import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from routes import control

@pytest.fixture
def context(monkeypatch):
    user={"user_id":42,"position":"УС","restaurant_key":"a","permissions":{"control_access":True}}
    monkeypatch.setattr(control,"control_user",AsyncMock(return_value=user))
    pool=MagicMock()
    conn=pool.acquire.return_value.__aenter__.return_value
    conn.fetchval=AsyncMock(side_effect=[1,2])
    conn.execute=AsyncMock()
    monkeypatch.setattr(control.db,"get_pool",lambda app:pool)
    return user,conn

def request(body):
    return SimpleNamespace(app={},json=AsyncMock(return_value=body))

@pytest.mark.parametrize(("body","expected"),[({"id":"123"},123),({"all":True},None)])
def test_read_scope(context,body,expected):
    _,conn=context
    response=asyncio.run(control.read_notifications(request(body)))
    assert response.status==200
    assert json.loads(response.text)=={"updated":1,"unread":2}
    sql,*args=conn.fetchval.call_args_list[0].args
    assert args==[42,["a"],expected]
    assert "recipient_id=$1" in sql and "restaurant_key=ANY($2)" in sql
    assert "read_at IS NULL" in sql
    assert response.headers["Cache-Control"]=="no-store"

@pytest.mark.parametrize("body",[{},{"id":123},{"id":"0"},{"id":"9223372036854775808"},{"all":True,"id":"1"},{"all":"true"},{"recipient_id":99,"id":"1"}])
def test_invalid_read(context,body):
    _,conn=context
    assert asyncio.run(control.read_notifications(request(body))).status==400
    conn.fetchval.assert_not_called()

def test_generation_scope_and_deduplication(context):
    user,conn=context
    asyncio.run(control.refresh_control_notifications(conn,user))
    sql,*args=conn.execute.call_args.args
    assert args==[42,["a"]]
    assert "ON CONFLICT (recipient_id,event_kind,source_id) DO NOTHING" in sql
    assert sql.count("restaurant_key=ANY($2)")==2

@pytest.mark.parametrize("handler",[control.notifications,control.read_notifications])
def test_guest_denied(context,handler):
    user,conn=context
    user["position"]="Тайный гость"
    assert asyncio.run(handler(request({"all":True}))).status==403
    conn.execute.assert_not_called()
    conn.fetchval.assert_not_called()
