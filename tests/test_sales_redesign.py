"""Sales corporate redesign integration contracts (no live database required)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend/sales.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend/sales.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend/sales.css").read_text(encoding="utf-8")


def test_sales_views_have_navigation():
    for view in ("overview", "restaurants", "products", "imports", "records", "settings"):
        assert f'data-view="{view}"' in HTML
    assert "state.view=button.dataset.view" in JS


def test_existing_sales_controls_preserved():
    for control in ("restaurant-select", "period-select", "btn-import-iiko",
                    "btn-detail", "btn-export", "upload-modal", "detail-modal",
                    "file-input", "upload-restaurant", "records-tbody"):
        assert f'id="{control}"' in HTML


def test_no_fake_sales_metrics_or_new_public_endpoints():
    assert "formatCurrency(overview.total_sales)" not in JS
    assert "Прибыль по отчёту" in JS
    for endpoint in ("/api/sales/dashboard", "/api/sales/restaurants",
                     "/api/sales/records", "/api/sales/upload", "/api/sales/export"):
        assert endpoint in JS


def test_mobile_layout_and_accessible_navigation():
    assert "@media(max-width:850px)" in CSS
    assert "@media(max-width:520px)" in CSS
    assert 'aria-label="Разделы Sales"' in HTML

def test_product_aggregation_scoped_and_bounded():
    source = (ROOT / "routes/sales.py").read_text(encoding="utf-8")
    section = source.split('async def sales_products(', 1)[1].split('@routes.post("/api/sales/records")', 1)[0]
    assert 'key not in allowed' in section
    assert 'sr.restaurant_key = ANY($2)' in section
    assert 'LIMIT 100' in section
    assert 'LIMIT 50' in section
    assert 'GROUP BY sr.product_name' in section


def test_products_and_records_are_real_api_backed_views():
    assert "'/api/sales/products'" in JS
    assert 'async function loadInlineRecords(' in JS
    assert "'/api/sales/records'" in JS
    assert 'esc(r.product_name' in JS


def test_iiko_daily_report_skips_hour_restaurant_and_day_totals():
    from datetime import datetime
    from openpyxl import Workbook
    from routes.sales import _parse_iiko_daily
    wb = Workbook()
    ws = wb.active
    ws.append(["Дневной отчет Воккер"])
    ws.append(["Название ресторана: Wokker - ЦО"])
    ws.append(["Период: с 22.11.2026 по 30.11.2026"])
    ws.append([None, None, None, None, "Итого"])
    ws.append(["Учетный день", "Торговое предприятие", "Час открытия",
               "Тип оплаты", "Сумма со скидкой, р.", "Чеков"])
    ws.append([datetime(2026, 11, 22), "Белая дача", "10", "ВТБ БАНК", 299, 1])
    ws.append([None, None, "12", "ВТБ БАНК", 7384, 8])
    ws.append([None, None, "12 всего", None, 7384, 8])
    ws.append([None, "Белая дача всего", None, None, 7683, 9])
    ws.append([None, "Беляево", "10", "Наличные", 1005, 1])
    ws.append(["22.11.2026 всего", None, None, None, 8688, 10])
    records = _parse_iiko_daily(ws)
    assert len(records) == 3
    assert sum(r["total_amount"] for r in records) == 8688
    assert sum(r["quantity"] for r in records) == 10
    assert [r["source_restaurant"] for r in records] == [
        "Белая дача", "Белая дача", "Беляево"]
    assert records[0]["opening_hour"] == 10
    assert all(r["product_name"] is None for r in records)


def test_multi_restaurant_upload_enforces_permissions_and_recalculates_each_restaurant():
    source = (ROOT / "routes/sales.py").read_text(encoding="utf-8")
    upload = source.split("async def upload_sales_file(", 1)[1].split(
        '@routes.post("/api/sales/dashboard")', 1)[0]
    assert 'if allowed is not None and rest_key not in allowed:' in upload
    assert 'if len(candidates) != 1:' in upload
    assert 'for rest_key, grouped in by_key.items():' in upload
    assert 'await _recalc_summary(conn, rest_key)' in upload


def test_hourly_iiko_parser_carries_hour_and_skips_subtotals():
    import openpyxl
    from routes.sales import _parse_iiko_daily
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Учетный день", "Торговое предприятие", "Час открытия", "Тип оплаты", "Сумма со скидкой", "Чеков"])
    from datetime import datetime
    ws.append([datetime(2026, 11, 22), "Беляево", 12, "ВТБ БАНК", 100, 2])
    ws.append([None, None, None, "Наличные", 50, 1])
    ws.append([None, None, "12 всего", None, 150, 3])
    ws.append([None, None, 13, "Яндекс.Еда", 200, 4])
    ws.append([None, "Беляево всего", None, None, 350, 7])
    ws.append([None, "Вернадка", 15, "ВТБ БАНК", 70, 1])
    rows = _parse_iiko_daily(ws)
    assert len(rows) == 4
    assert [r["opening_hour"] for r in rows] == [12, 12, 13, 15]
    assert sum(r["total_amount"] for r in rows) == 420
    assert rows[-1]["source_restaurant"] == "Вернадка"


def test_hourly_dashboard_uses_scoped_sales_and_real_check_counts():
    source = (ROOT / "routes/sales.py").read_text(encoding="utf-8")
    assert "GROUP BY hour ORDER BY hour" in source
    assert "sr.extra_data::jsonb->>'opening_hour'" in source
    assert '"hourly_revenue":' in source
    assert 'hourly_revenue:hourly=[]' in JS
    assert 'Почасовая выручка' in JS


def test_order_type_mapping_is_persistent_and_authorized():
    source = (ROOT / "routes/sales.py").read_text(encoding="utf-8")
    assert 'CREATE TABLE IF NOT EXISTS sales_order_type_settings' in (ROOT / "database/004_sales_order_type_settings.sql").read_text(encoding="utf-8")
    assert 'if action == "save" and not user.get("is_super_admin"):' in source
    assert '"Не распределено"' in source
    assert 'order_mapping.get(method, "Не распределено")' in source
    assert '"by_order_type": list(order_types.values())' in source
    assert 'loadOrderTypeSettings()' in JS
    assert 'Выручка по типу заказа' in JS


def test_multi_restaurant_name_prefix_normalization():
    import re
    source = (ROOT / "routes/sales.py").read_text(encoding="utf-8")
    assert 'r"^\\s*(?:wokker|воккер)\\s*[-–—:]\\s*"' in source
    pattern = r"^\s*(?:wokker|воккер)\s*[-–—:]\s*"
    assert re.sub(pattern, "", "WOKKER - Белая дача", flags=re.I) == "Белая дача"
    assert re.sub(pattern, "", "Воккер: Беляево", flags=re.I) == "Беляево"


def test_order_type_mapping_accepts_postgres_jsonb_text_and_dict():
    import asyncio
    from routes.sales import _order_type_mapping

    class Conn:
        def __init__(self, value):
            self.value = value

        async def fetchval(self, *_args):
            return self.value

    expected = {"Наличные": "Зал", "Яндекс.Еда": "Доставка"}
    assert asyncio.run(_order_type_mapping(Conn('{"Наличные":"Зал","Яндекс.Еда":"Доставка"}'))) == expected
    assert asyncio.run(_order_type_mapping(Conn(expected))) == expected


def test_global_order_type_edit_permission_is_super_admin_only():
    source = (ROOT / "routes/sales.py").read_text(encoding="utf-8")
    assert 'if action == "save" and not user.get("is_super_admin"):' in source
    assert '"can_edit": bool(user.get("is_super_admin"))' in source


def test_order_type_schema_is_migrated_not_created_on_requests():
    source = (ROOT / "routes/sales.py").read_text(encoding="utf-8")
    migration = (ROOT / "database/004_sales_order_type_settings.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS sales_order_type_settings" in migration
    assert "CREATE TABLE IF NOT EXISTS sales_order_type_settings" not in source
    assert "SELECT mapping FROM sales_order_type_settings" in source
