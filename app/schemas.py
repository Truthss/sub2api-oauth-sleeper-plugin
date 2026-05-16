from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class PageMeta(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int


class SleeperEvent(BaseModel):
    id: int | None = None
    account_id: int
    account_name: str | None = None
    platform: str
    window_name: str
    utilization_percent: float
    threshold_percent: float
    reset_at: datetime
    previous_rate_limit_reset_at: datetime | None = None
    created_at: datetime | None = None


class SleeperEventPage(BaseModel):
    items: list[SleeperEvent]
    meta: PageMeta


class SettingsOut(BaseModel):
    enabled: bool
    threshold_percent: float
    scan_interval_seconds: int
    include_openai: bool
    include_anthropic: bool
    last_scan_at: datetime | None = None
    last_scan_scanned: int = 0
    last_scan_triggered: int = 0


class SettingsUpdate(BaseModel):
    enabled: bool
    threshold_percent: float = Field(gt=0, le=100)
    scan_interval_seconds: int = Field(ge=15, le=3600)
    include_openai: bool = True
    include_anthropic: bool = True


class ScanResult(BaseModel):
    scanned: int
    triggered: int
    events: list[SleeperEvent]


class StatusOut(BaseModel):
    enabled: bool
    threshold_percent: float
    scan_interval_seconds: int
    include_openai: bool
    include_anthropic: bool
    last_scan_at: datetime | None = None
    last_scan_scanned: int = 0
    last_scan_triggered: int = 0
    sleeping_count: int = 0
    sleeping_accounts: list[SleeperEvent]
