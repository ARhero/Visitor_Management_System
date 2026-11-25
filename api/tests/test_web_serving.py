"""Serving the built web app from the API (WEB_DIST_DIR, used by serve-public.bat)."""

import mimetypes

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import _serve_web


async def test_scripts_are_javascript_even_if_windows_says_text(tmp_path, monkeypatch):
    # Some Windows registries map .js to text/plain; browsers then refuse to run modules.
    monkeypatch.setitem(mimetypes.types_map, ".js", "text/plain")
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>VMS</title>")
    (tmp_path / "assets" / "index-abc.js").write_text("export {};")
    (tmp_path / "assets" / "index-abc.css").write_text("body{}")
    (tmp_path / "manifest.webmanifest").write_text("{}")
    (tmp_path / "sw.js").write_text("")
    app = FastAPI()
    _serve_web(app, tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        js = await c.get("/assets/index-abc.js")
        assert js.headers["content-type"].startswith("text/javascript")
        assert "immutable" in js.headers["cache-control"]
        assert (await c.get("/sw.js")).headers["content-type"].startswith("text/javascript")
        assert (await c.get("/assets/index-abc.css")).headers["content-type"].startswith("text/css")
        manifest = await c.get("/manifest.webmanifest")
        assert manifest.headers["content-type"].startswith("application/manifest+json")
        # App routes get the page; API paths and files outside dist never do.
        page = await c.get("/admin/people")
        assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
        assert (await c.get("/api/v1/nope")).status_code == 404
        outside = await c.get("/..%2F..%2Fsecret.txt")
        assert outside.headers["content-type"].startswith("text/html")  # index.html, not a file
