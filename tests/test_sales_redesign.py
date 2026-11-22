"""Sales corporate redesign integration contracts (no live database required)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend/sales.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend/sales.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend/sales.css").read_text(encoding="utf-8")


def test_sales_views_have_navigation():
    for view in ("overview", "restaurants", "products", "imports", "records"):
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
