"""
Базовые unit-тесты для проекта Wokker Bot.
Запуск: python -m pytest tests/ -v
"""
import pytest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.security import (
    hash_password,
    verify_password,
    sanitize_html,
    validate_login_data,
    _check_rate_limit,
    _reset_rate_limit,
)
from utils.common import safe_int, safe_float, generate_login_for
from config import LOGIN_RE, PERM_KEYS


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

    def test_validate_login_data(self):
        ok, err = validate_login_data({"login": "ADM01", "password": "secret"})
        assert err is None
        assert ok == {"login": "adm01", "password": "secret"}

        bad, err = validate_login_data({"login": "bad_login", "password": "secret"})
        assert bad is None
        assert err == "invalid_login_format"

    def test_rate_limit_blocks_after_five(self):
        ip = "127.0.0.99"
        _reset_rate_limit(ip)
        try:
            for _ in range(5):
                assert _check_rate_limit(ip) is True
            assert _check_rate_limit(ip) is False
        finally:
            _reset_rate_limit(ip)


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
        login = generate_login_for("Иванов Иван", existing)
        assert LOGIN_RE.match(login)

    def test_generate_login_for_unique(self):
        existing = {"iva10", "iva11"}
        login = generate_login_for("Иванов Иван", existing)
        assert login not in existing
        assert LOGIN_RE.match(login)


# ===================== ROUTES / CONFIG CONSTANTS TESTS =====================
class TestRoutesAndConfig:
    def test_login_format_regex(self):
        assert LOGIN_RE.match("abc01")
        assert LOGIN_RE.match("xyz99")
        assert LOGIN_RE.match("adm01")
        assert LOGIN_RE.match("a1b01") is None
        assert LOGIN_RE.match("ABc01") is None

    def test_permissions_list_complete(self):
        assert "timesheet_access" in PERM_KEYS
        assert "users_create" in PERM_KEYS
        assert "users_edit" in PERM_KEYS


# ===================== DATE VALIDATION TESTS =====================
class TestDateValidation:
    def test_parse_date_valid_formats(self):
        from datetime import datetime
        test_cases = [
            ("2024-01-15", "%Y-%m-%d", "2024-01-15"),
            ("15.01.2024", "%d.%m.%Y", "2024-01-15"),
        ]
        for val, fmt, expected in test_cases:
            parsed = datetime.strptime(val, fmt)
            assert parsed.strftime("%Y-%m-%d") == expected
