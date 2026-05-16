from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import init_db, close_db
from .schemas import SettingsOut, SettingsUpdate, ScanResult, StatusOut, SleeperEventPage
from . import repository as repo
from . import scanner

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db(settings)
    await scanner.start_background()
    yield
    await scanner.stop_background()
    await close_db()


app = FastAPI(title="Sub2API OAuth Sleeper Plugin", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    settings = get_settings()
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Do not set frame-ancestors here. The plugin is served under the same LAN
    # origin as Sub2API and must be embeddable by Sub2API's custom-menu iframe.
    return response


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/admin")
async def admin_page():
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/static/app.js")
async def app_js(request: Request):
    content = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    return Response(
        content,
        media_type="text/javascript; charset=utf-8",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/static/style.css")
async def style_css(request: Request):
    content = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    return Response(
        content,
        media_type="text/css; charset=utf-8",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/api/settings", response_model=SettingsOut)
async def get_settings_api():
    return await repo.get_settings()


@app.put("/api/settings", response_model=SettingsOut)
async def put_settings_api(data: SettingsUpdate):
    return await repo.update_settings(data)


@app.post("/api/scan-once", response_model=ScanResult)
async def scan_once_api():
    return await scanner.scan_once(force=True)


@app.get("/api/events", response_model=SleeperEventPage)
async def events_api(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=10)):
    return await repo.list_events_page(page=page, page_size=page_size)


@app.get("/api/sleeping-accounts", response_model=SleeperEventPage)
async def sleeping_accounts_api(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=10)):
    return await repo.list_sleeping_accounts_page(page=page, page_size=page_size)


@app.get("/api/status", response_model=StatusOut)
async def status_api():
    s = await repo.get_settings()
    sleeping_page = await repo.list_sleeping_accounts_page(page=1, page_size=10)
    return StatusOut(
        enabled=s.enabled,
        threshold_percent=s.threshold_percent,
        scan_interval_seconds=s.scan_interval_seconds,
        max_sleep_per_scan=s.max_sleep_per_scan,
        include_openai=s.include_openai,
        include_anthropic=s.include_anthropic,
        last_scan_at=s.last_scan_at,
        last_scan_scanned=s.last_scan_scanned,
        last_scan_triggered=s.last_scan_triggered,
        sleeping_count=sleeping_page.meta.total,
        sleeping_accounts=sleeping_page.items,
    )
