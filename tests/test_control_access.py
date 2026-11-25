from types import SimpleNamespace
from routes.control import control_allowed, token_hash

def test_explicit_permission():
    assert control_allowed({"permissions": {"control_access": True}})
    assert not control_allowed({"permissions": {"sales_access": True}})
    assert not control_allowed({"permissions": {"control_access": "true"}})
    assert not control_allowed({"is_admin": True})
    assert not control_allowed({"permissions": "invalid"})

def test_super_and_fired():
    assert control_allowed({"is_super_admin": True})
    assert not control_allowed({"is_super_admin": True, "is_fired": True})
    assert not control_allowed({"permissions": {"control_access": True}, "is_fired": True})

def test_bearer_only():
    assert token_hash(SimpleNamespace(headers={}, query={"token": "a"*64})) is None
    assert token_hash(SimpleNamespace(headers={"Authorization": "Bearer short"})) is None
    assert token_hash(SimpleNamespace(headers={"Authorization": "Bearer "+"a"*64})) is not None
