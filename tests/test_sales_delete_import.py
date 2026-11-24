"""Regression contracts for deleting iiko imports safely."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_delete_import_requires_auth_and_checks_all_restaurants():
    source = (ROOT / "routes/sales.py").read_text(encoding="utf-8")
    route = source.split('async def delete_sales_import(', 1)[1].split('@routes.post("/api/sales/dashboard")', 1)[0]
    assert '@sales_required' in source.split('async def delete_sales_import(', 1)[0][-100:]
    assert 'allowed = await _sales_restaurant_scope(request)' in route
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


def test_sales_writes_share_bounded_transaction_lock():
    source = (ROOT / "routes/sales.py").read_text(encoding="utf-8")
    upload = source.split("async def upload_sales_file(", 1)[1].split("DEFAULT_ORDER_TYPES", 1)[0]
    delete = source.split("async def delete_sales_import(", 1)[1].split("@routes.post", 1)[0]
    for route in (upload, delete):
        assert route.index("SET LOCAL lock_timeout") < route.index("pg_advisory_xact_lock(814726, 1)")
        assert route.index("pg_advisory_xact_lock(814726, 1)") < route.index("FOR NO KEY UPDATE")
        assert "LockNotAvailableError, DeadlockDetectedError, QueryCanceledError" in route
        assert "status=409" in route
    assert 'imp["status"] == "processing"' in delete
    assert "FOR UPDATE" not in delete
