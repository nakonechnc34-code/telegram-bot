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
    for item in ("sales-v2-dashboard", "sales-v2-kpis", "sales-leading-chart",
                 "sales-v2-restaurant-panel", "rest-restaurant-check",
                 "sales-v2-presets"):
        assert item in JS
        assert item in CSS
    for label in ("ТОВАРООБОРОТ", "Средний чек", "Чеки", "Гости", "Доля доставки"):
        assert label in JS


def test_unavailable_metrics_not_fabricated():
    # The dashboard must not manufacture receipt counts, average receipt or discounts
    # when the iiko summary does not expose reliable values.
    overview = JS.split("function renderDashboard(data)", 1)[1].split(
        "async function loadOrderTypeSettings()", 1
    )[0]
    assert "kpi('₽','Продажи'" in overview
    assert "kpi('%','Доля доставки',total>0?" in overview
    assert "kpi('▤','Средний чек',o.avg_check==null?'—'" in overview
    assert "kpi('▣','Чеки',o.checks==null?'—'" in overview
    assert "kpi('%','Скидки',o.discounts==null?'—'" in overview
    assert overview.index("sales-compact-kpis") < overview.index("sales-chart-filter-layout")
    assert 'metrics[coverage] == metrics["rows_count"]' in API
    assert 'sales / result["checks"] if result["checks"] else None' in API


def test_restaurant_scope_still_uses_authorized_dashboard_endpoint():
    assert "'/api/sales/dashboard'" in JS
    assert "allowed = await _allowed_rests(user)" in API


def test_restaurant_turnover_api_still_provides_channel_split():
    assert '"restaurant_channels": restaurant_channels' in API
    assert 'restaurant_channel_rows = await conn.fetch(' in API
    assert 'FROM sales_records sr {w}' in API
    assert 'restaurant_channels.setdefault(' in API


def test_turnover_chart_defaults_to_today_and_ends_dashboard():
    html = (ROOT / "frontend/sales.html").read_text(encoding="utf-8")
    assert '<option value="1d" selected>Сегодня</option>' in html
    assert "period: '1d'" in JS
    assert "sales-leading-chart" in JS
    dashboard = JS.split("'<div class=\"sales-v2-dashboard\">", 1)[1].split(
        "DOM.content.querySelectorAll('[data-rest-period]')", 1
    )[0]
    assert dashboard.strip().endswith("'</div></div>';")
    for token in ("restaurantTurnoverPanel", "sales-v3-context-strip",
                  "sales-v4-secondary-stats", "sales-v4-layout", "sales-v4-insights"):
        assert token not in dashboard
    for key in ("total", "hall", "delivery", "previous"):
        assert f'data-sales-chart-series="{key}"' in JS
    assert "turnoverChart.granularity==='hour'" in JS


def test_turnover_chart_uses_scoped_current_and_comparison_periods():
    assert '"turnover_chart": chart_series' in API
    assert 'chart_previous_from = date_from - timedelta(days=7) if days == 1 else previous_from' in API
    assert 'chart_previous_where, _ = _where(previous_conditions, chart_previous_params)' in API
    assert 'FROM sales_records sr {w}' in API
    assert 'FROM sales_records sr {chart_previous_where}' in API
    assert '"granularity": "hour" if days == 1 else "day"' in API


def test_turnover_chart_marks_missing_dates_instead_of_plotting_zero():
    assert '"has_data": i in chart_current_points' in API
    assert '"previous_has_data": i in chart_previous_points' in API
    assert "if(!hasData(p,key)){drawing=false;return;}" in JS
    assert "visible.filter(key=>hasData(p,key))" in JS


def test_dashboard_heading_uses_selected_dates_not_only_imported_dates():
    assert "const availableDates=DOM.dateFrom.value&&DOM.dateTo.value?" in JS


def test_kpi_comparison_uses_same_scoped_window_as_chart():
    assert "period_metrics(chart_previous_where, chart_previous_params, prior_sales)" in API
    assert 'overview["previous_metrics"]' in API
    for field in ("total_sales", "avg_check", "checks", "discounts", "delivery_share"):
        assert "prior." + field in JS
    assert "previous==null?'Нет данных'" in JS


def test_turnover_comparison_follows_selected_channels():
    assert "channels.forEach(key=>" in JS
    assert "const priorKey='previous_'+key" in JS
    assert "(p.previous||{})[key]" in JS
    assert "color:series[key].color" in JS
    assert "ctx.setLineDash(item.previous?[6,4]:[])" in JS
