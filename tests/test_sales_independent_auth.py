"""Sales must use independent credentials and an explicitly granted permission."""
from pathlib import Path
from routes.sales import _sales_allowed

ROOT = Path(__file__).resolve().parents[1]


def test_sales_access_is_explicit_even_for_super_admin():
    assert not _sales_allowed({"is_super_admin": True, "permissions": {}})
    assert not _sales_allowed({"is_admin": True, "permissions": {"users_edit": True}})
    assert _sales_allowed({"is_admin": True, "permissions": {"sales_access": True}})
    assert not _sales_allowed({"permissions": {"sales_access": True}, "is_fired": True})
    assert not _sales_allowed({"permissions": '{"sales_access": "true"}'})
    assert _sales_allowed({"is_admin": True, "permissions": '{"sales_access": true}'})


def test_sales_endpoints_do_not_accept_admin_sessions():
    src = (ROOT / "routes/sales.py").read_text(encoding="utf-8")
    assert "JOIN users u ON u.user_id = ss.user_id" in src
    assert "ss.expires_at > NOW()" in src
    assert "hashlib.sha256(token.encode" in src
    assert "get_admin_user" not in src
    assert "@require_admin" not in src
    assert "@admin_required" not in src
    assert src.count("@sales_required") >= 9
    assert 'if not _sales_allowed(user):' in src


def test_sales_login_is_independent_and_has_logout():
    src = (ROOT / "frontend/sales.js").read_text(encoding="utf-8")
    assert "sessionStorage.getItem('wokker_sales_token')" in src
    assert "'/api/sales/login'" in src
    assert "'/api/sales/logout'" in src
    assert "'/api/sales/me'" in src
    assert "wokker_admin_token" not in src
    html = (ROOT / "frontend/sales.html").read_text(encoding="utf-8")
    assert 'href="/admin"' not in html
    assert 'id="sales-login-form"' in html
    assert 'id="sales-logout"' in html


def test_permission_configured_in_admin_panel_and_session_migrated():
    config = (ROOT / "config.py").read_text(encoding="utf-8")
    assert '"key": "sales_access"' in config
    assert '"label": "Доступ к WOKKER Sales"' in config
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '005_sales_sessions.sql' in app
    sql = (ROOT / "database/005_sales_sessions.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS sales_sessions" in sql
    assert "expires_at" in sql
