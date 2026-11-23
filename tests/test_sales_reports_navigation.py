"""Static navigation and reporting contracts for WOKKER Sales."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend/sales.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend/sales.js").read_text(encoding="utf-8")


def test_three_primary_sales_sections():
    assert 'data-view="overview"><span>◫</span> Дашборд' in HTML
    assert 'data-view="reports"><span>▦</span> Отчёты' in HTML
    assert 'data-view="imports"><span>⇧</span> Импорт iiko' in HTML
    assert 'data-view="settings"' in HTML


def test_automatic_reports_derive_from_filtered_dashboard():
    assert "else if(view==='reports')" in JS
    assert "Динамика выручки по дням" in JS
    assert "Товарооборот по ресторанам" in JS
    assert "Типы заказов: сравнение периодов" in JS
    assert "Почасовая выручка" in JS
    assert "Зал и доставка по часам" in JS
    assert "esc(t.typ)" in JS
    assert "reportList.map(item=>table(" in JS


def test_iiko_import_still_has_upload_and_delete():
    assert "else if(view==='imports')" in JS
    assert "importRows(imports)" in JS
    assert "deleteImport(Number(button.dataset.importId))" in JS
    assert "'/api/sales/imports/delete'" in JS
