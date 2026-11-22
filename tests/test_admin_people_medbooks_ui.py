"""Guard employee and medbook functionality during CSS-only redesign."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1] / "frontend"

def test_page_style_hook_and_scoped_selectors():
    js = (ROOT / "admin.js").read_text(encoding="utf-8")
    css = (ROOT / "admin-soft-depth.css").read_text(encoding="utf-8")
    assert "$('page-content').dataset.page = page;" in js
    assert '[data-page="users"]' in css
    assert '[data-page="medbooks"]' in css

def test_employee_permissions_search_and_actions_remain():
    js = (ROOT / "admin.js").read_text(encoding="utf-8")
    for item in ("users_create", "users_edit", "users_fire", "users-search",
                 "restoreUser(", "fireUser(", "openEditUser(", "openAddUser(",
                 "/api/admin/users"):
        assert item in js

def test_medbook_permissions_tabs_and_actions_remain():
    js = (ROOT / "admin.js").read_text(encoding="utf-8")
    for item in ("medbook_edit", "medbook_doctors_manage",
                 "medbook_tests_manage", "medbook_vaccines_manage",
                 "data-mt=\"staff\"", "data-mt=\"doctors\"",
                 "data-mt=\"tests\"", "data-mt=\"vaccines\"",
                 "openEditMedbook(", "/api/admin/medbooks"):
        assert item in js
