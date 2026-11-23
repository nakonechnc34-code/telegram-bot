"""Sales role access regression tests."""
import pytest

from routes.sales import _sales_allowed


@pytest.mark.parametrize("permissions", [None, {}, {"sales_access": False}, "invalid json", '{"sales_access":false}'])
def test_superadmin_has_implicit_sales_access(permissions):
    assert _sales_allowed({"is_super_admin": True, "permissions": permissions})


def test_superadmin_still_requires_active_account():
    assert not _sales_allowed({"is_super_admin": True, "is_fired": True})
    assert not _sales_allowed(None)


@pytest.mark.parametrize("permissions,expected", [
    (None, False),
    ({}, False),
    ({"sales_access": False}, False),
    ({"sales_access": True}, True),
    ('{"sales_access":true}', True),
    ('{"sales_access":false}', False),
    ("invalid json", False),
])
def test_regular_admin_requires_explicit_sales_permission(permissions, expected):
    assert _sales_allowed({"is_admin": True, "permissions": permissions}) is expected


def test_regular_user_cannot_gain_access_with_permission_flag():
    assert not _sales_allowed({"permissions": {"sales_access": True}})
    assert not _sales_allowed({"is_admin": True, "is_fired": True, "permissions": {"sales_access": True}})
