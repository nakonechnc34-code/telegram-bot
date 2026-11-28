from routes.control import task_manager

def test_manager_requires_control_access():
    assert not task_manager({"permissions":{"control_manage":True}})
    assert not task_manager({"is_super_admin":True,"is_fired":True})

def test_explicit_management_permission():
    assert task_manager({"permissions":{"control_access":True,"control_manage":True}})
    assert not task_manager({"permissions":{"control_access":True,"control_manage":"true"}})
    assert not task_manager({"permissions":{"control_access":True}})

from routes.control import control_network_view, control_template_edit

def test_network_view_and_admin_edit():
    base={"permissions":{"control_access":True}}
    assert control_network_view(dict(base,position="Территориальный управляющий"))
    assert control_network_view({"permissions":{"control_access":True,"control_view_all":True}})
    assert not control_network_view(base)
    assert control_template_edit(dict(base,is_admin=True))
    assert not control_template_edit(base)
    us={"position":"УС","is_admin":True,"permissions":{"control_access":True,"control_view_all":True}}
    assert not control_network_view(us)
    assert not control_template_edit(us)


import asyncio
import pytest
from routes.control import control_allowed, restaurant_scope

@pytest.mark.parametrize(("role", "expected_scope", "editor"), [
    ({"is_super_admin": True}, None, True),
    ({"position": "HR", "is_admin": True}, ["a"], True),
    ({"position": "Администратор", "is_admin": True}, ["a"], True),
    ({"position": "Территориальный управляющий"}, None, False),
    ({"position": "УС", "is_admin": True}, ["a"], False),
    ({"position": "Работник"}, [], False),
    ({"position": "Тайный гость", "is_admin": True}, [], False),
])
def test_role_scope_and_template_permissions(role, expected_scope, editor):
    user = {"restaurant_key": "a", "permissions": {"control_access": True}, **role}
    assert asyncio.run(restaurant_scope(user)) == expected_scope
    assert control_template_edit(user) == editor

def test_guest_cannot_inherit_management_permissions():
    guest = {"position": "Тайный гость", "is_admin": True, "restaurant_key": "a",
             "permissions": {"control_access": True, "control_manage": True, "control_view_all": True}}
    assert control_allowed(guest)
    assert not task_manager(guest)
    assert not control_network_view(guest)
    assert not control_template_edit(guest)
    assert asyncio.run(restaurant_scope(guest)) == []

def test_us_cannot_inherit_network_scope():
    user = {"position": "УС", "restaurant_key": "a",
            "permissions": {"control_access": True, "control_view_all": True}}
    assert asyncio.run(restaurant_scope(user)) == ["a"]

@pytest.mark.parametrize("role", [
    {"position":"HR","is_admin":True},
    {"position":"Администратор","is_admin":True},
    {"position":"Территориальный управляющий"},
    {"position":"УС"},
    {"position":"Тайный гость"},
])
def test_role_requires_explicit_access_and_revocation(role):
    assert not control_allowed(dict(role, permissions={}))
    assert control_allowed(dict(role, permissions={"control_access":True}))
    assert not control_allowed(dict(role, permissions={"control_access":"true"}))
    assert not control_allowed(dict(role, permissions={"control_access":True}, is_fired=True))

@pytest.mark.parametrize("role", [{"position":"Работник"}, {"position":"Кассир"}, {"position":"Повар"}])
def test_ordinary_employee_access_flag_alone_is_insufficient(role):
    assert not control_allowed(dict(role, permissions={"control_access":True}))

def test_super_admin_access_and_revocation():
    assert control_allowed({"is_super_admin":True})
    assert not control_allowed({"is_super_admin":True,"is_fired":True})
