"""
Unit-тесты для декораторов доступа и логики проверки ответов/дат.
Запуск: python -m pytest tests/test_routes.py -v
"""
import os
import sys
import asyncio
import datetime
import pytest
from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from middleware.auth import require_auth, require_admin, require_perm, require_super_admin
from utils.auth_helpers import _sync_user_has_perm, _is_tu
from routes.medbooks import parse_date_ddmmYYYY, add_months, compute_medbook_status


class TestAuthDecorators:
    def test_require_perm_without_user_returns_401(self):
        async def _run_test():
            @require_perm("users_edit")
            async def dummy(request):
                return None

            req = make_mocked_request("POST", "/api/admin/user/update")
            resp = await dummy(req)
            assert resp.status == 401

        asyncio.run(_run_test())

    def test_require_perm_forbidden_for_regular_admin(self):
        async def _run_test():
            @require_perm("users_fire")
            async def dummy(request):
                return None

            req = make_mocked_request("POST", "/api/admin/user/fire")
            req["user"] = {
                "user_id": 10,
                "is_admin": True,
                "is_super_admin": False,
                "position": "Менеджер",
                "permissions": {"users_edit": True},
            }
            resp = await dummy(req)
            assert resp.status == 403

        asyncio.run(_run_test())

    def test_require_perm_allows_hr_and_super_admin(self):
        async def _run_test():
            @require_perm("users_fire")
            async def dummy(request):
                return "ok"

            req_hr = make_mocked_request("POST", "/api/admin/user/fire")
            req_hr["user"] = {
                "user_id": 11,
                "is_admin": True,
                "is_super_admin": False,
                "position": "HR",
                "permissions": {},
            }
            assert await dummy(req_hr) == "ok"

            req_super = make_mocked_request("POST", "/api/admin/user/fire")
            req_super["user"] = {
                "user_id": 12,
                "is_admin": True,
                "is_super_admin": True,
                "position": "Администратор",
                "permissions": {},
            }
            assert await dummy(req_super) == "ok"

        asyncio.run(_run_test())

    def test_require_super_admin_blocks_non_super(self):
        async def _run_test():
            @require_super_admin
            async def dummy(request):
                return "ok"

            req = make_mocked_request("POST", "/api/admin/super")
            req["user"] = {"user_id": 10, "is_admin": True, "is_super_admin": False}
            resp = await dummy(req)
            assert resp.status == 403

        asyncio.run(_run_test())

    def test_is_tu_detection(self):
        assert _is_tu({"position": "Территориальный управляющий", "is_super_admin": False}) is True
        assert _is_tu({"position": "HR", "is_super_admin": False}) is False
        assert _is_tu({"position": "Территориальный управляющий", "is_super_admin": True}) is False


class TestMedbookHelpers:
    def test_parse_date_ddmmYYYY_valid_and_invalid(self):
        assert parse_date_ddmmYYYY("20.11.2026") == datetime.date(2026, 11, 20)
        assert parse_date_ddmmYYYY("31.02.2026") is None
        assert parse_date_ddmmYYYY("2026-11-20") is None
        assert parse_date_ddmmYYYY("") is None

    def test_add_months_clamps_end_of_month(self):
        d = datetime.date(2024, 1, 31)
        assert add_months(d, 1) == datetime.date(2024, 2, 29)

    def test_compute_medbook_status_missing_is_invalid(self):
        doctors = [{"id": 1, "validity_months": 12}]
        tests = []
        vaccines = []
        assert compute_medbook_status({}, doctors, tests, vaccines) == "invalid"
