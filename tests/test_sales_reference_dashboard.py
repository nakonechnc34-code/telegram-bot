"""Contracts for the Restalytica-inspired WOKKER dashboard."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend/sales.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend/sales.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend/sales.css").read_text(encoding="utf-8")
API = (ROOT / "routes/sales.py").read_text(encoding="utf-8")


def test_dashboard_period_presets_supported_by_api():
    for period in ("1d", "7d", "30d", "90d", "365d", "custom"):
        assert f'value="{period}"' in HTML
    for period in ('"1d": 1', '"7d": 7', '"30d": 30', '"90d": 90', '"365d": 365'):
        assert period in API


def test_reference_dashboard_layout():
    for item in ("sales-v2-dashboard", "sales-v2-kpis", "sales-v2-trend",
                 "sales-v2-restaurant-panel", "rest-restaurant-check",
                 "sales-v2-presets", "sales-v2-compare-grid"):
        assert item in JS
        assert item in CSS
    for label in ("Товарооборот", "Предыдущий период", "Выручка по часам",
                  "Рестораны с продажами", "Динамика", "Каналы продаж"):
        assert label in JS


def test_unavailable_metrics_not_fabricated():
    # The dashboard must not manufacture receipt counts, average receipt or discounts
    # when the iiko summary does not expose reliable values.
    overview = JS.split("function renderDashboard(data)", 1)[1].split(
        "async function loadOrderTypeSettings()", 1
    )[0]
    assert "kpi('₽','Товарооборот'" in overview
    assert "kpi('↗','Предыдущий период'" in overview
    assert "kpi('⌁','Рестораны с продажами'" in overview
    assert "kpi('₽','Средний чек'" not in overview
    assert "kpi('₽','Скидки'" not in overview
    assert "formatNumber(h.checks)" not in overview


def test_restaurant_scope_still_uses_authorized_dashboard_endpoint():
    assert "'/api/sales/dashboard'" in JS
    assert "allowed = await _allowed_rests(user)" in API
