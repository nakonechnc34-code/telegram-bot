"""Ensure startup registers every CONTROL SQL migration in order."""
import ast
from pathlib import Path


def test_control_migrations_registered_in_startup():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "app.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_migrations")
    registered = [
        n.value for n in sorted(
            (n for n in ast.walk(fn) if isinstance(n, ast.Constant)
             and isinstance(n.value, str) and n.value.endswith(".sql")),
            key=lambda n: (n.lineno, n.col_offset))
    ]
    expected = sorted(p.name for p in (root / "database").glob("*_control_*.sql"))
    assert expected
    assert [name for name in registered if name in expected] == expected
