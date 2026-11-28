import pytest
from routes.control import valid_control_id

@pytest.mark.parametrize("value", [None, True, False, 0, -1, 2**63, 10**100, "1", 1.0, [], {}])
def test_invalid_control_id(value):
    assert not valid_control_id(value)

@pytest.mark.parametrize("value", [1, 42, 2**63-1])
def test_valid_control_id(value):
    assert valid_control_id(value)

import asyncio
from unittest.mock import AsyncMock, Mock, patch
from routes import control

@pytest.mark.parametrize("handler,field,extra", [
    ("task_history","id",{}),
    ("haccp_readings","equipment_id",{"start":"2026-11-01","end":"2026-11-02"}),
    ("read_document","version_id",{}),
    ("list_check_photos","id",{}),
    ("task_photos","id",{}),
])
@pytest.mark.parametrize("value",[0,-1,True,2**63,10**100,"1"])
def test_invalid_identifier_rejected_before_database(handler,field,extra,value):
    request=Mock()
    request.json=AsyncMock(return_value={**extra,field:value})
    with patch.object(control,"control_user",AsyncMock(return_value={"user_id":1})), patch.object(control,"restaurant_scope",AsyncMock()) as scope, patch.object(control.db,"get_pool") as pool:
        response=asyncio.run(getattr(control,handler)(request))
        assert response.status==400
        scope.assert_not_awaited()
        pool.assert_not_called()
