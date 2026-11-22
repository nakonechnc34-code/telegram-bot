"""Regression checks for additive migrations required by content API handlers.

These checks do not connect to production PostgreSQL. Real schema upgrade
must also be validated against a restored database before deployment.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "003_content_schema_compat.sql"


def test_content_compat_migration_is_registered():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'cur.execute((migrations / "003_content_schema_compat.sql").read_text(encoding="utf-8"))' in app


def test_news_and_standards_restaurant_key_added_idempotently():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "ALTER TABLE news ADD COLUMN IF NOT EXISTS restaurant_key TEXT;" in sql
    assert "ALTER TABLE standards ADD COLUMN IF NOT EXISTS restaurant_key TEXT;" in sql


def test_certification_legacy_data_is_preserved():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "ALTER TABLE certification_questions ADD COLUMN IF NOT EXISTS options JSONB;" in sql
    assert "ALTER TABLE certification_questions ADD COLUMN IF NOT EXISTS correct_index INTEGER;" in sql
    assert "WHERE options IS NULL" in sql
    assert "WHERE correct_index IS NULL" in sql
    for field in ("option_a", "option_b", "option_c", "option_d", "correct_option"):
        assert f"column_name = '{field}'" in sql
    for letter, index in (("a", 0), ("b", 1), ("c", 2), ("d", 3)):
        assert f"WHEN ''{letter}'' THEN {index}" in sql
    assert "DROP TABLE" not in sql.upper()
    assert "DROP COLUMN" not in sql.upper()


def test_content_api_queries_use_columns_created_by_migration():
    content = (ROOT / "routes" / "content.py").read_text(encoding="utf-8")
    sql = MIGRATION.read_text(encoding="utf-8")
    for column in ("n.restaurant_key", "s.restaurant_key"):
        assert column in content
    for column in ("options", "correct_index"):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in sql
