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
    for item in ("rest-dashboard", "rest-kpis", "rest-graph", "rest-restaurants",
                 "rest-restaurant-check", "rest-date-presets"):
        assert item in JS
        assert item in CSS
    for label in ("Продажи", "Средний чек", "Чеки", "Скидки", "Динамика"):
        assert label in JS


def test_unavailable_metrics_not_fabricated():
    assert "Нет количества чеков в данных iiko" in JS
    assert "Нет данных о скидках" in JS


def test_restaurant_scope_still_uses_authorized_dashboard_endpoint():
    assert "'/api/sales/dashboard'" in JS
    assert "allowed = await _allowed_rests(user)" in API
