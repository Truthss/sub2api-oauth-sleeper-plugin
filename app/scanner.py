from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from . import repository as repo
from .schemas import ScanResult, SleeperEvent

_scan_lock = asyncio.Lock()
_stop_event: asyncio.Event | None = None
_background_task: asyncio.Task | None = None


@dataclass
class Decision:
    window_name: str
    utilization_percent: float
    reset_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _float(extra: dict[str, Any], key: str) -> float | None:
    v = extra.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e11:
            ts = ts / 1000
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return _time(float(text))
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _choose(candidates: list[Decision]) -> Decision | None:
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.reset_at)


def evaluate_openai(account: dict[str, Any], threshold: float, now: datetime) -> Decision | None:
    extra = account.get("extra") or {}
    candidates: list[Decision] = []
    p5 = _float(extra, "codex_5h_used_percent")
    r5 = _time(extra.get("codex_5h_reset_at"))
    if p5 is not None and r5 is not None and r5 > now and p5 >= threshold:
        candidates.append(Decision("5h", p5, r5))
    p7 = _float(extra, "codex_7d_used_percent")
    r7 = _time(extra.get("codex_7d_reset_at"))
    if p7 is not None and r7 is not None and r7 > now and p7 >= threshold:
        candidates.append(Decision("7d", p7, r7))
    return _choose(candidates)


def evaluate_anthropic(account: dict[str, Any], threshold: float, now: datetime) -> Decision | None:
    extra = account.get("extra") or {}
    candidates: list[Decision] = []
    raw5 = _float(extra, "session_window_utilization")
    r5 = _time(account.get("session_window_end"))
    if raw5 is not None:
        p5 = raw5 * 100
        if r5 is not None and r5 > now and p5 >= threshold:
            candidates.append(Decision("5h", p5, r5))
    raw7 = _float(extra, "passive_usage_7d_utilization")
    r7 = _time(extra.get("passive_usage_7d_reset"))
    if raw7 is not None:
        p7 = raw7 * 100
        if r7 is not None and r7 > now and p7 >= threshold:
            candidates.append(Decision("7d", p7, r7))
    return _choose(candidates)


def evaluate_account(account: dict[str, Any], threshold: float, now: datetime) -> Decision | None:
    platform = account.get("platform")
    if platform == "openai":
        return evaluate_openai(account, threshold, now)
    if platform == "anthropic":
        return evaluate_anthropic(account, threshold, now)
    return None


async def scan_once(force: bool = False) -> ScanResult:
    async with _scan_lock:
        settings = await repo.get_settings()
        if not settings.enabled and not force:
            await repo.update_last_scan(0, 0)
            return ScanResult(scanned=0, triggered=0, events=[])
        accounts = await repo.list_oauth_accounts(settings.include_openai, settings.include_anthropic)
        now = _now()
        events: list[SleeperEvent] = []
        for account in accounts:
            decision = evaluate_account(account, settings.threshold_percent, now)
            if decision is None:
                continue
            prev = account.get("rate_limit_reset_at")
            if prev is not None:
                prev_dt = _time(prev)
                if prev_dt is not None and prev_dt >= decision.reset_at:
                    continue
            updated = await repo.set_rate_limited(account["id"], decision.reset_at)
            if not updated:
                continue
            event = await repo.insert_event(
                SleeperEvent(
                    account_id=account["id"],
                    account_name=account.get("name"),
                    platform=account.get("platform") or "",
                    window_name=decision.window_name,
                    utilization_percent=decision.utilization_percent,
                    threshold_percent=settings.threshold_percent,
                    reset_at=decision.reset_at,
                    previous_rate_limit_reset_at=_time(prev),
                )
            )
            events.append(event)
        await repo.update_last_scan(len(accounts), len(events))
        return ScanResult(scanned=len(accounts), triggered=len(events), events=events)


async def _loop() -> None:
    global _stop_event
    _stop_event = asyncio.Event()
    while not _stop_event.is_set():
        try:
            settings = await repo.get_settings()
            if settings.enabled:
                await scan_once()
            wait_seconds = max(15, settings.scan_interval_seconds)
        except Exception:
            wait_seconds = 60
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=wait_seconds)
        except asyncio.TimeoutError:
            pass


async def start_background() -> None:
    global _background_task
    if _background_task is None or _background_task.done():
        _background_task = asyncio.create_task(_loop())


async def stop_background() -> None:
    global _stop_event, _background_task
    if _stop_event is not None:
        _stop_event.set()
    if _background_task is not None:
        await _background_task
    _background_task = None
    _stop_event = None
