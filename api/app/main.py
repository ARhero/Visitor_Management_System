import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from app.api.v1 import (
    auth,
    blacklist,
    dashboard,
    form_config,
    guard,
    host,
    invites,
    onboarding,
    org,
    platform,
    privacy,
    public,
    push,
    sites,
    users,
    visits_log,
    webhooks,
)
from app.core.config import get_settings
from app.core.db import admin_engine, dispose_engines
from app.core.errors import install_error_handlers
from app.core.redis import close_redis, get_redis


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    sweeper = None
    if s.run_jobs_in_process and s.env != "test":  # tests call the sweep directly
        from app.workers.tasks import run_forever

        sweeper = asyncio.create_task(run_forever())
    yield
    if sweeper:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper
    from app.workers.queue import close_queue

    await close_queue()
    await dispose_engines()
    await close_redis()


# File types for the web app, set here rather than asked of the operating system: on some
# Windows computers the registry maps .js to text/plain, and browsers then refuse to run
# the app's scripts ("Expected a JavaScript module script... MIME type text/plain").
WEB_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".json": "application/json",
    ".webmanifest": "application/manifest+json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".wasm": "application/wasm",
    ".txt": "text/plain",
}


def _serve_web(app: FastAPI, dist: Path) -> None:
    """The built web app: files as they are, every other path gets index.html (the app
    routes in the browser). Hashed assets are cached for a year, the rest not at all."""
    dist = dist.resolve()
    index = dist / "index.html"
    if not index.is_file():
        raise RuntimeError(f"WEB_DIST_DIR has no index.html: {dist} (run npm run build in web/)")

    @app.get("/{path:path}", include_in_schema=False)
    async def web(path: str) -> Response:
        if path.startswith("api/"):
            return JSONResponse({"error": {"code": "not_found", "message": "Not found"}}, 404)
        f = (dist / path).resolve()
        if path and f.is_file() and f.is_relative_to(dist):
            cache = (
                "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            )
            return FileResponse(
                f, media_type=WEB_TYPES.get(f.suffix.lower()), headers={"Cache-Control": cache}
            )
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="VMS API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs" if s.env != "prod" else None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)

    v1 = APIRouter(prefix="/api/v1")
    for r in (
        auth.router,
        platform.router,
        org.router,
        onboarding.router,
        sites.router,
        users.router,
        form_config.router,
        public.router,
        host.router,
        push.router,
        guard.router,
        invites.router,
        blacklist.router,
        dashboard.router,
        dashboard.public_router,
        privacy.router,
        privacy.public_router,
        visits_log.router,
        webhooks.router,
    ):
        v1.include_router(r)
    if s.env in ("dev", "test"):
        v1.include_router(webhooks.dev_router)  # mock WhatsApp inbox
    app.include_router(v1)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> dict[str, str]:
        async with admin_engine().connect() as c:
            await c.execute(text("SELECT 1"))
        await get_redis().ping()
        return {"status": "ready"}

    if s.web_dist_dir:  # last: its catch-all route must not hide the ones above
        _serve_web(app, Path(s.web_dist_dir))
    return app


app = create_app()
