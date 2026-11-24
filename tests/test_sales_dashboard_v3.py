"""Dashboard V3 visual contracts — no fabricated metrics or changed authorization."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "frontend/sales.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend/sales.css").read_text(encoding="utf-8")


def test_dashboard_retains_visual_hierarchy():
    for token in ("sales-kpi-comparison", "sales-compact-kpis",
                  "sales-leading-chart", "sales-v2-restaurant-panel"):
        assert token in JS
        assert token in CSS


def test_dashboard_retains_authorized_data_and_filters():
    for token in ("'/api/sales/dashboard'", "DOM.restaurantSelect.value",
                  "DOM.periodSelect.value", "rest-restaurant-check"):
        assert token in JS
    assert "kpi('₽','Средний чек'" not in JS
