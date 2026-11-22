"""Regression checks for legacy standards.category compatibility."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_standards_category_migration_is_additive():
    sql = (ROOT / "database" / "003_content_schema_compat.sql").read_text(encoding="utf-8")
    assert "ALTER TABLE standards ADD COLUMN IF NOT EXISTS category TEXT;" in sql
    assert "UPDATE standards SET category = group_name" in sql
    assert "WHERE category IS NULL AND group_name IS NOT NULL" in sql
    assert "DROP TABLE" not in sql.upper()
    assert "DROP COLUMN" not in sql.upper()


def test_standards_list_and_write_paths_expect_category():
    content = (ROOT / "routes" / "content.py").read_text(encoding="utf-8")
    assert "s.category" in content
    assert "(title, body, category, file_url, author_id, restaurant_key, status)" in content


def test_migration_runs_before_app_starts():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'cur.execute((migrations / "003_content_schema_compat.sql").read_text(encoding="utf-8"))' in app
