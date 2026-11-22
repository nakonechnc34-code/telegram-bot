"""Static smoke checks for Soft Depth assets (no production DB required)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "frontend"

def test_soft_depth_assets_are_wired():
    html = (ROOT / "admin.html").read_text(encoding="utf-8")
    assert 'href="/admin-soft-depth.css"' in html
    assert 'src="/admin-dashboard-soft-depth.js"' in html
    assert html.index('src="/admin.js"') < html.index('src="/admin-dashboard-soft-depth.js"')

def test_dashboard_preserves_existing_endpoint_and_router():
    js = (ROOT / "admin-dashboard-soft-depth.js").read_text(encoding="utf-8")
    assert "PAGE_LOADERS.dashboard = loadSoftDepthDashboard" in js
    assert "/api/admin/dashboard/summary" in js
    for metric in ("stat-active", "stat-pending", "stat-medbooks", "stat-questions"):
        assert metric in js
    assert "esc(title)" in js and "esc(detail)" in js

def test_design_supports_mobile_and_accessible_focus():
    css = (ROOT / "admin-soft-depth.css").read_text(encoding="utf-8")
    assert "@media (max-width: 720px)" in css
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css
