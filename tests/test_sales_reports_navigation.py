"""Static navigation and reporting contracts for WOKKER Sales."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend/sales.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend/sales.js").read_text(encoding="utf-8")


def test_three_primary_sales_sections():
    for view, title in (("overview", "Дашборд"), ("reports", "Отчёты"),
                        ("imports", "Импорт iiko"), ("settings", "Настройки")):
        assert f'data-view="{view}"' in HTML
        assert f"<span>{title}</span>" in HTML


def test_reports_tab_displays_catalog():
    assert "else if(view==='reports')" in JS
    reports = JS.split("} else if(view==='reports') {", 1)[1].split("} else if(view==='imports') {", 1)[0]
    assert reports.strip() == "renderReportCatalog();"
    assert "Сравнение ежечастно" in JS
    assert "reportList.map(item=>table(" not in JS


def test_iiko_import_still_has_upload_and_delete():
    assert "else if(view==='imports')" in JS
    assert "importRows(imports)" in JS
    assert "deleteImport(Number(button.dataset.importId))" in JS
    assert "'/api/sales/imports/delete'" in JS


def test_hourly_report_uses_assigned_territories_and_scoped_restaurants():
    api = (ROOT / "routes/sales.py").read_text(encoding="utf-8")
    report = api.split('async def sales_hourly_comparison', 1)[1].split('async def sales_dashboard', 1)[0]
    assert 'r.territory_manager_id' in report
    assert 'u.user_id = r.territory_manager_id' in report
    assert '_sales_restaurant_scope(request)' in report
    assert 'WHERE r.key = ANY($1)' in report
    assert 'restaurant_key = ANY($4::text[])' in report
    assert 'r.territory_manager_id' in JS
    assert "sum('current',g.items)" in JS
    assert 'Без территории' in JS


def test_catalog_opens_hourly_report_and_returns_to_list():
    assert "const salesReportCatalog=[" in JS
    assert "open:renderHourlyComparison" in JS
    assert "salesReportCatalog[Number(button.dataset.reportIndex)].open()" in JS
    assert 'id="sales-report-back"' in JS
    assert "getElementById('sales-report-back').addEventListener('click',renderReportCatalog)" in JS
    assert "'/api/sales/hourly-comparison'" in JS
