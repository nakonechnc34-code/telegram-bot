"""Regression contracts for deleting iiko imports safely."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_delete_import_requires_auth_and_checks_all_restaurants():
    source = (ROOT / "routes/sales.py").read_text(encoding="utf-8")
    route = source.split('async def delete_sales_import(', 1)[1].split('@routes.post("/api/sales/dashboard")', 1)[0]
    assert '@admin_required' in source.split('async def delete_sales_import(', 1)[0][-100:]
    assert 'allowed = await _allowed_rests(user)' in route
    assert 'keys.issubset(set(allowed))' in route
    assert 'SELECT DISTINCT restaurant_key FROM sales_records WHERE import_id=$1' in route
    assert 'async with conn.transaction():' in route


def test_delete_import_preserves_other_imports_and_refreshes_totals():
    source = (ROOT / "routes/sales.py").read_text(encoding="utf-8")
    route = source.split('async def delete_sales_import(', 1)[1].split('@routes.post("/api/sales/dashboard")', 1)[0]
    assert 'DELETE FROM sales_records WHERE import_id=$1' in route
    assert 'await _recalc_summary(conn, key)' in route
    assert 'DELETE FROM sales_imports WHERE id=$1' in route
    assert 'DELETE FROM sales_records WHERE restaurant_key=' not in route


def test_import_history_has_delete_confirmation_and_refresh():
    source = (ROOT / "frontend/sales.js").read_text(encoding="utf-8")
    assert 'sales-delete-import' in source
    assert "window.confirm(" in source
    assert "'/api/sales/imports/delete'" in source
    assert 'await loadDashboard()' in source
