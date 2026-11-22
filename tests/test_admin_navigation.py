"""Regression checks: Soft Blue navigation keeps existing routes and security hooks."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1] / "frontend"

def test_navigation_keeps_every_existing_page():
    html = (ROOT / "admin.html").read_text(encoding="utf-8")
    pages = re.findall(r'<button class="nav-item" data-page="([^"]+)"', html)
    assert pages == [
        "dashboard", "users", "medbooks", "news", "standards", "certification",
        "faq", "restaurants", "positions", "citizenships", "questions",
        "admins", "reports", "audit",
    ]
    assert 'id="nav-admins" style="display:none;"' in html

def test_navigation_preserves_important_controls():
    html = (ROOT / "admin.html").read_text(encoding="utf-8")
    for element in ("logout-btn", "change-password-btn", "hamburger", "overlay",
                    "q-count", "news-pending-count", "standards-pending-count"):
        assert f'id="{element}"' in html

def test_navigation_headings_are_present_and_visual_only():
    html = (ROOT / "admin.html").read_text(encoding="utf-8")
    assert html.count('class="sd-nav-heading" role="presentation"') == 6
    css = (ROOT / "admin-soft-depth.css").read_text(encoding="utf-8")
    assert ".sd-nav-heading" in css
    assert ":focus-visible" in css
