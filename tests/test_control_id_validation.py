import pytest
from routes.control import valid_control_id

@pytest.mark.parametrize("value", [None, True, False, 0, -1, 2**63, 10**100, "1", 1.0, [], {}])
def test_invalid_control_id(value):
    assert not valid_control_id(value)

@pytest.mark.parametrize("value", [1, 42, 2**63-1])
def test_valid_control_id(value):
    assert valid_control_id(value)
