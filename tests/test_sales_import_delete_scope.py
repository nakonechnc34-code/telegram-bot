"""Contracts for scoped Sales import deletion and visible user feedback."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = (ROOT / "routes/sales.py").read_text(encoding="utf-8")
FRONTEND = (ROOT / "frontend/sales.js").read_text(encoding="utf-8")


def test_deletion_checks_every_restaurant_in_import():
    deletion = BACKEND.split('async def delete_sales_import(', 1)[1].split('@routes.post("/api/sales/dashboard")', 1)[0]
    assert 'SELECT DISTINCT restaurant_key FROM sales_records WHERE import_id=$1' in deletion
    assert 'keys.issubset(set(allowed))' in deletion
    assert 'DELETE FROM sales_records WHERE import_id=$1' in deletion
    assert 'async with conn.transaction()' in deletion


def test_import_list_exposes_same_delete_eligibility():
    assert 'AS can_delete' in BACKEND
    assert 'NOT EXISTS (SELECT 1 FROM sales_records sr WHERE sr.import_id = si.id' in BACKEND
    assert 'sr.restaurant_key = ANY($2::text[])' in BACKEND
    assert 'if allowed is not None else "TRUE"' in BACKEND
    assert '*([scoped_keys, allowed] if scoped_keys is not None and allowed is not None' in BACKEND
    assert '"can_delete": i["can_delete"]' in BACKEND


def test_ui_prevents_forbidden_deletion():
    assert 'imp.can_delete === false' in FRONTEND
    assert 'Нет прав на удаление' in FRONTEND
    assert 'Обратитесь к супер-администратору' in FRONTEND
