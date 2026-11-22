"""Phase 4: remaining pages keep their route and loader wiring."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1] / "frontend"
PAGES = ("news", "standards", "certification", "faq", "restaurants",
         "positions", "citizenships", "questions", "admins", "reports", "audit")

def test_remaining_pages_keep_navigation_and_loader():
    html = (ROOT / "admin.html").read_text(encoding="utf-8")
    js = (ROOT / "admin.js").read_text(encoding="utf-8")
    for page in PAGES:
        assert f'data-page="{page}"' in html
        assert f"{page}:" in js or f"'{page}':" in js

def test_remaining_pages_have_scoped_soft_blue_styles():
    css = (ROOT / "admin-soft-depth.css").read_text(encoding="utf-8")
    for page in PAGES:
        assert f'[data-page="{page}"]' in css
    assert "overflow-x:auto" in css
    assert ":focus-visible" in css

def test_existing_admin_api_and_permissions_still_present():
    js = (ROOT / "admin.js").read_text(encoding="utf-8")
    for function in ("loadNews", "loadStandards", "loadCertification", "loadFAQ",
                     "loadRestaurants", "loadPositions", "loadCitizenships",
                     "loadQuestions", "loadReports", "loadAudit"):
        assert f"function {function}(" in js
    assert "hasPerm(" in js
