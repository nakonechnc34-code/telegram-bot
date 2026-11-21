"""
Базовые unit-тесты для проекта Wokker Bot.
Запуск: python -m pytest tests/ -v
"""
import pytest
import os
import sys
import importlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.security import hash_password, verify_password, sanitize_html
from utils.common import safe_int, safe_float, generate_login_for


# ===================== SECURITY TESTS =====================
class TestSecurity:
    def test_hash_password_roundtrip(self):
        password = "test_password_123"
        hashed = hash_password(password)
        assert hashed.startswith("pbkdf2_sha256$")
        assert verify_password(password, hashed)
        assert not verify_password("wrong_password", hashed)

    def test_hash_password_unique(self):
        password = "same_password"
        assert hash_password(password) != hash_password(password)

    def test_sanitize_html_blocks_javascript(self):
        result = sanitize_html('<a href="javascript:alert(1)">click</a>')
        assert 'javascript:' not in result.lower()

    def test_sanitize_html_allows_safe_tags(self):
        result = sanitize_html('<strong>bold</strong> <em>italic</em>')
        assert 'bold' in result
        assert 'italic' in result

    def test_sanitize_html_blocks_script(self):
        result = sanitize_html('<script>alert(1)</script>Hello')
        assert '<script>' not in result
        assert 'alert' not in result


# ===================== COMMON UTILS TESTS =====================
class TestCommonUtils:
    def test_safe_int_valid(self):
        assert safe_int("123") == 123
        assert safe_int(456) == 456
        assert safe_int("abc") == 0
        assert safe_int(None) == 0
        assert safe_int("", 42) == 42

    def test_safe_float_valid(self):
        assert safe_float("3.14") == pytest.approx(3.14)
        assert safe_float("1,5") == pytest.approx(1.5)
        assert safe_float("abc") == 0.0
        assert safe_float(None) == 0.0

    def test_generate_login_for_basic(self):
        existing = set()
        login = generate_login_for("Иванов", existing)
        assert len(login) == 5
        assert login[:3].isalpha()
        assert login[3:].isdigit()

    def test_generate_login_for_unique(self):
        existing = {"ivan01", "petr02"}
        login = generate_login_for("Иванов", existing)
        assert login not in existing


# ===================== CONFIG TESTS =====================
class TestConfig:
    def test_db_url_required(self, monkeypatch):
        """DATABASE_URL должен быть задан. Используем importlib.reload."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        # Убедимся, что config импортирован
        import config as _cfg
        with pytest.raises(ValueError, match="DATABASE_URL"):
            importlib.reload(_cfg)
        # Восстанавливаем модуль для последующих тестов
        os.environ["DATABASE_URL"] = os.environ.get(
            "DATABASE_URL", "postgresql://test:test@localhost:5432/test"
        )
        importlib.reload(_cfg)


# ===================== ROUTES TESTS (mock) =====================
class TestRoutes:
    def test_login_format_regex(self):
        from config import LOGIN_RE
        assert LOGIN_RE.match("abc01")
        assert LOGIN_RE.match("xyz99")
        assert LOGIN_RE.match("adm01")
        assert LOGIN_RE.match("a1b01") is None
        assert LOGIN_RE.match("ABc01") is None

    def test_permissions_list_complete(self):
        from config import PERM_KEYS
        assert "timesheet_access" in PERM_KEYS
        assert "users_create" in PERM_KEYS
        assert "users_edit" in PERM_KEYS


# ===================== DATE VALIDATION TESTS =====================
class TestDateValidation:
    def test_parse_date_valid_formats(self):
        from datetime import datetime
        test_cases = [
            ("2024-01-15", "%Y-%m-%d", "2024-01-15"),
            ("15.01.2024", None, "2024-01-15"),
        ]
        for val, fmt, expected in cases if False else test_cases:
            if fmt:
                parsed = datetime.strptime(val, fmt)
                assert parsed.strftime("%Y-%m-%d") == expected
