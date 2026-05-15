from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import init_db, close_db
from .schemas import SettingsOut, SettingsUpdate, ScanResult, StatusOut, SleeperEvent
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
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/admin")
async def admin_page():
    settings = get_settings()
    base_path = settings.public_base_path.rstrip("/")
    text = (STATIC_DIR / "index.html").read_text(encoding="utf-8").replace(
        "window.OAUTH_SLEEPER_BASE_PATH = document.currentScript.dataset.basePath || '';",
        f"window.OAUTH_SLEEPER_BASE_PATH = {base_path!r};",
    )
    return HTMLResponse(text)


@app.get("/api/settings", response_model=SettingsOut)
async def get_settings_api():
    return await repo.get_settings()


@app.put("/api/settings", response_model=SettingsOut)
async def put_settings_api(data: SettingsUpdate):
    return await repo.update_settings(data)


@app.post("/api/scan-once", response_model=ScanResult)
async def scan_once_api():
    return await scanner.scan_once(force=True)


@app.get("/api/events", response_model=list[SleeperEvent])
async def events_api(limit: int = Query(default=50, ge=1, le=200)):
    return await repo.list_events(limit)


@app.get("/api/status", response_model=StatusOut)
async def status_api():
    s = await repo.get_settings()
    sleeping = await repo.list_sleeping_accounts()
    return StatusOut(
        enabled=s.enabled,
        threshold_percent=s.threshold_percent,
        scan_interval_seconds=s.scan_interval_seconds,
        include_openai=s.include_openai,
        include_anthropic=s.include_anthropic,
        last_scan_at=s.last_scan_at,
        last_scan_scanned=s.last_scan_scanned,
        last_scan_triggered=s.last_scan_triggered,
        sleeping_accounts=sleeping,
    )
