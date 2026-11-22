"""Regression tests for Soft Blue static asset HTTP routes.

Keep these tests independent of database configuration and app startup.
"""
import ast
import asyncio
from pathlib import Path

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "app.py").read_text(encoding="utf-8")
TREE = ast.parse(APP_SOURCE)

ASSETS = [
    ("/admin-soft-depth.css", "admin-soft-depth.css", "text/css", "handle_admin_soft_depth_css"),
    (
        "/admin-dashboard-soft-depth.js",
        "admin-dashboard-soft-depth.js",
        "application/javascript",
        "handle_admin_dashboard_soft_depth_js",
    ),
]


def _asset_app():
    """Execute only the relevant production handlers and route registrations."""
    handler_names = {"_send_static_file"} | {row[3] for row in ASSETS}
    handlers = [
        node for node in TREE.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name in handler_names
    ]
    assert len(handlers) == len(handler_names)
    namespace = {
        "web": web,
        "formatdate": __import__("email.utils", fromlist=["formatdate"]).formatdate,
        "_STATIC_FILES_CACHE": {},
    }
    namespace["_serve_file"] = lambda filename, cache: (
        (ROOT / "frontend" / filename).read_bytes(),
        (ROOT / "frontend" / filename).stat().st_mtime,
    )
    exec(compile(ast.Module(body=handlers, type_ignores=[]), "app.py", "exec"), namespace)
    app = web.Application()
    for url, filename, content_type, handler in ASSETS:
        assert (ROOT / "frontend" / filename).is_file()
        app.router.add_get(url, namespace[handler])
        # Verify the real app registers the exact URL and handler.
        assert any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_get"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == url
            and isinstance(node.args[1], ast.Name)
            and node.args[1].id == handler
            for statement in TREE.body
            for node in ast.walk(statement)
        )
    return app


@pytest.mark.parametrize("url,filename,content_type,handler", ASSETS)
def test_soft_blue_asset_http_response(url, filename, content_type, handler):
    from aiohttp.test_utils import TestClient, TestServer

    async def run():
        async with TestClient(TestServer(_asset_app())) as client:
            response = await client.get(url)
            assert response.status == 200
            assert response.content_type == content_type
            assert await response.read() == (ROOT / "frontend" / filename).read_bytes()

    asyncio.run(run())


def test_admin_html_references_soft_blue_assets():
    html = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
    for url, _, _, _ in ASSETS:
        assert f'"{url}"' in html
