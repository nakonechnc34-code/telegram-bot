"""Design system contracts for the independent WOKKER Sales workspace."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend/sales.html").read_text(encoding="utf-8")
CSS = (ROOT / "frontend/sales.css").read_text(encoding="utf-8")
JS = (ROOT / "frontend/sales.js").read_text(encoding="utf-8")


def test_all_sales_sections_share_one_workspace():
    for view in ("overview", "reports", "imports", "settings"):
        assert f'data-view="{view}"' in HTML
    assert 'id="sales-page-content"' in HTML
    assert "sales-section-stats" in JS
    assert "sales-workflow-card" in JS
    assert "sales-import-hero" in JS


def test_separate_sales_login_and_authorized_api_unchanged():
    assert 'id="sales-login-form"' in HTML
    assert "'/api/sales/login'" in JS
    assert "'/api/sales/me'" in JS
    assert "'/api/sales/logout'" in JS
    assert 'wokker_sales_token' in JS
    assert 'Вернуться в админ' not in HTML


def test_accessibility_and_responsive_design():
    assert 'aria-label="Закрыть окно загрузки"' in HTML
    assert 'aria-label="Закрыть детализацию"' in HTML
    assert 'prefers-reduced-motion:reduce' in CSS
    assert 'focus-visible' in CSS
    assert '.sales-section-stats' in CSS
    assert '@media(max-width:520px)' in CSS


def test_reports_catalog_without_affecting_imports():
    reports = JS.split("} else if(view==='reports') {", 1)[1].split("} else if(view==='imports') {", 1)[0]
    assert reports.strip() == "renderReportCatalog();"
    assert "Сравнение ежечастно" in JS
    assert "imports.length" in JS
    assert "Замена данных" in JS
