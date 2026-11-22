"""Regression checks for Sales scope, CSV import and frontend rendering."""
from pathlib import Path
from routes.sales import _parse_csv

ROOT = Path(__file__).resolve().parents[1]


def test_semicolon_csv_import_with_russian_headers():
    rows = _parse_csv('дата;товар;количество;сумма\n2026-11-20;Лапша;2;500\n')
    assert len(rows) == 1
    assert rows[0]['product_name'] == 'Лапша'
    assert rows[0]['quantity'] == 2
    assert rows[0]['total_amount'] == 500


def test_sales_dashboard_scopes_all_queries_to_allowed_restaurants():
    source = (ROOT / 'routes/sales.py').read_text(encoding='utf-8')
    dashboard = source.split('async def sales_dashboard(', 1)[1].split('@routes.post("/api/sales/records")', 1)[0]
    assert 'key = key or (allowed[0]' not in dashboard
    assert 'scoped_keys = [key] if key else allowed' in dashboard
    assert 'sr.restaurant_key = ANY($2)' in dashboard
    assert 'WHERE r.key = ANY($2)' in dashboard
    assert 'WHERE si.restaurant_key = ANY($1)' in dashboard
    assert 'AND restaurant_key = ANY($2)' in dashboard


def test_sales_ui_escapes_user_supplied_values_and_filters_records():
    source = (ROOT / 'frontend/sales.js').read_text(encoding='utf-8')
    assert 'esc(r.name)' in source
    assert 'esc(imp.filename)' in source
    assert '${esc(r.product_name ||' in source
    assert "document.getElementById('detail-search-product').value" in source
    assert "document.getElementById('detail-date-from').value" in source
    assert '<div class="kpi-trend up">+10%</div>' not in source
    assert '<div class="kpi-trend up">+15%</div>' not in source


def test_sales_upload_is_bounded_and_rejects_empty_rows():
    source = (ROOT / 'routes/sales.py').read_text(encoding='utf-8')
    assert '10 * 1024 * 1024 + 1' in source
    assert 'if not records:' in source
