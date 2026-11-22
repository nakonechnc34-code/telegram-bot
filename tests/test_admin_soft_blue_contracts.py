"""Cross-phase contract tests for the Soft Blue admin redesign.

These tests are structural guards, not substitutes for browser/end-to-end testing.
"""
from pathlib import Path
import re

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
HTML = (FRONTEND / "admin.html").read_text(encoding="utf-8")
JS = (FRONTEND / "admin.js").read_text(encoding="utf-8")
CSS = (FRONTEND / "admin-soft-depth.css").read_text(encoding="utf-8")
PAGES = (
    "dashboard", "users", "medbooks", "news", "standards", "certification",
    "faq", "restaurants", "positions", "citizenships", "questions",
    "admins", "reports", "audit",
)

def test_all_navigation_destinations_and_loaders():
    nav = re.findall(r'<button class="nav-item" data-page="([^"]+)"', HTML)
    assert tuple(nav) == PAGES
    titles = JS.split("const PAGE_TITLES =", 1)[1].split("};", 1)[0]
    loaders = JS.split("const PAGE_LOADERS =", 1)[1].split("};", 1)[0]
    for page in PAGES:
        assert re.search(rf"\b{page}\s*:", titles)
        assert re.search(rf"\b{page}\s*:", loaders)

def test_auth_and_permissions_remain_wired():
    assert "/api/admin/login" in JS
    assert "/api/admin/me" in JS
    assert "function hasPerm(perm)" in JS
    assert "ME.permissions[perm]" in JS
    assert "adminsNav.style.display = ME.is_super_admin ? 'flex' : 'none'" in JS
    assert 'id="nav-admins" style="display:none;"' in HTML
    assert "getToken()" in JS and "showLogin()" in JS
    assert "function closeSidebar()" in JS

def test_employee_lifecycle_and_search():
    for expected in (
        "/api/admin/users", "users-search", "currentTab === 'fired'",
        "currentSearch", "openAddUser()", "openEditUser(", "fireUser(",
        "restoreUser(", "hasPerm('users_create')", "hasPerm('users_edit')",
        "hasPerm('users_fire')",
    ):
        assert expected in JS

def test_medbook_tabs_statuses_and_permissions():
    for expected in (
        "/api/admin/medbooks", "data-mt=\"staff\"", "data-mt=\"doctors\"",
        "data-mt=\"tests\"", "data-mt=\"vaccines\"",
        "medbook_status === 'ok'", "medbook_status === 'expiring'",
        "medbook_status === 'invalid'", "openEditMedbook(",
        "hasPerm('medbook_edit')",
    ):
        assert expected in JS

def test_modals_counters_and_responsive_css():
    for element in ("modal-overlay", "modal-body", "modal-footer",
                    "hamburger", "overlay", "q-count", "news-pending-count",
                    "standards-pending-count"):
        assert f'id="{element}"' in HTML
    for fn in ("openModal(", "closeModal(", "refreshCounters("):
        assert fn in JS
    assert "max-width:720px" in CSS or "max-width: 720px" in CSS
    assert "overflow-x:auto" in CSS
    assert ":focus-visible" in CSS

def test_redesign_is_isolated_from_existing_routing():
    assert "$('page-content').dataset.page = page;" in JS
    assert "const loader = PAGE_LOADERS[page]" in JS
    assert "loader().then(" in JS
    assert '<link rel="stylesheet" href="/admin-soft-depth.css">' in HTML
    assert '<script src="/admin.js"></script>' in HTML
