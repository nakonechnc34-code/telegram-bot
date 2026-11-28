import asyncio
from aiohttp.test_utils import make_mocked_request
from aiohttp import web
from app import clean_platform_url_middleware

def test_clean_platform_urls():
    async def handler(request):
        return web.Response(text="ok")
    for path in ("/", "/sales", "/timesheet", "/admin", "/academy", "/sales/"):
        request = make_mocked_request("GET", path + "?utm_source=chatgpt.com&utm_medium=link")
        response = asyncio.run(clean_platform_url_middleware(request, handler))
        assert response.status == 302
        assert response.headers["Location"] == path

def test_preserve_functional_parameters():
    async def handler(request):
        return web.Response(text="ok")
    request = make_mocked_request("GET", "/timesheet?from=admin&utm_source=chatgpt.com&date=2026-11-25&x=1&x=2")
    response = asyncio.run(clean_platform_url_middleware(request, handler))
    assert response.headers["Location"] == "/timesheet?from=admin&date=2026-11-25&x=1&x=2"

def test_api_and_clean_pages_unchanged():
    async def handler(request):
        return web.Response(text="ok")
    for method, path in (("GET", "/api/health?utm_source=test"), ("GET", "/sales?date=2026-11-25"), ("POST", "/sales?utm_source=test")):
        response = asyncio.run(clean_platform_url_middleware(make_mocked_request(method, path), handler))
        assert response.status == 200
