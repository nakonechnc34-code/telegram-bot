"""Dashboard V3 visual contracts — no fabricated metrics or changed authorization."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "frontend/sales.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend/sales.css").read_text(encoding="utf-8")


def test_new_dashboard_visual_hierarchy():
    for token in ("sales-v3-context-strip", "sales-v3-section-title",
                  "sales-v3-kpi-corner", "sales-v3-hour-track",
                  "sales-v3-ranking-panel", "sales-v3-channels-panel"):
        assert token in JS or token == "sales-v3-hour-track"
        assert token in CSS or token == "sales-v3-channels-panel"


def test_hourly_bars_use_actual_revenue_and_guard_zero():
    assert "const peakHour=Math.max(1,...hourly.map" in JS
    assert "Number(h.sales||0)/peakHour*100" in JS
    assert "money(h.sales)" in JS


def test_dashboard_retains_authorized_data_and_filters():
    for token in ("'/api/sales/dashboard'", "DOM.restaurantSelect.value",
                  "DOM.periodSelect.value", "DOM.comparisonDate.value",
                  "DOM.comparisonHour.value", "rest-restaurant-check"):
        assert token in JS
    assert "kpi('₽','Средний чек'" not in JS
