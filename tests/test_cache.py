"""
Unit-тесты для модуля кэширования справочных данных.
Запуск: python -m pytest tests/test_cache.py -v
"""
import os
import sys
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from middleware.cache import get_cached, set_cached, clear_cache


class TestCache:
    def setup_method(self):
        clear_cache()

    def teardown_method(self):
        clear_cache()

    def test_set_and_get_cached_value(self):
        set_cached("restaurants_all", [{"key": "r1", "name": "Ресторан 1"}], ttl=60)
        assert get_cached("restaurants_all") == [{"key": "r1", "name": "Ресторан 1"}]

    def test_expired_entry_returns_none(self, monkeypatch):
        now = 1_700_000_000.0
        monkeypatch.setattr(time, "time", lambda: now)
        set_cached("faq_list", ["q1"], ttl=10)
        assert get_cached("faq_list") == ["q1"]

        monkeypatch.setattr(time, "time", lambda: now + 11)
        assert get_cached("faq_list") is None

    def test_clear_single_and_all_keys(self):
        set_cached("k1", "v1", ttl=60)
        set_cached("k2", "v2", ttl=60)

        clear_cache("k1")
        assert get_cached("k1") is None
        assert get_cached("k2") == "v2"

        clear_cache()
        assert get_cached("k2") is None
