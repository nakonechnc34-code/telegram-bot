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


def test_reports_tab_is_completely_empty():
    assert "else if(view==='reports')" in JS
    reports = JS.split("} else if(view==='reports') {", 1)[1].split("} else if(view==='imports') {", 1)[0]
    assert reports.strip() == "DOM.content.innerHTML='';"
    assert "reportList.map(item=>table(" not in JS


def test_iiko_import_still_has_upload_and_delete():
    assert "else if(view==='imports')" in JS
    assert "importRows(imports)" in JS
    assert "deleteImport(Number(button.dataset.importId))" in JS
    assert "'/api/sales/imports/delete'" in JS
