from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from . import repository as repo
from . import scheduler_refresh
from .schemas import ScanResult, SleeperEvent

_scan_lock = asyncio.Lock()
_stop_event: asyncio.Event | None = None
_background_task: asyncio.Task | None = None


@dataclass
class Decision:
    window_name: str
    utilization_percent: float
    reset_at: datetime


@dataclass
class ScanDependencies:
    get_settings: Callable[[], Awaitable[Any]]
    list_oauth_accounts: Callable[[bool, bool], Awaitable[list[dict[str, Any]]]]
    set_rate_limited: Callable[[int, datetime], Awaitable[bool]]
    insert_event: Callable[[SleeperEvent], Awaitable[SleeperEvent]]
    update_last_scan: Callable[[int, int], Awaitable[None]]
    rollback_sleeps: Callable[[list[int]], Awaitable[None]]
    now: Callable[[], datetime]
    refresh_scheduler: Callable[[], bool]
    verify_model: Callable[[], bool]
    verify_after_sleep: Callable[[], bool]


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


def select_sleep_candidates(
    accounts: list[dict[str, Any]],
    threshold: float,
    now: datetime,
    platform: str,
    max_sleep_per_scan: int,
) -> list[tuple[dict[str, Any], Decision]]:
    """Return sleep candidates capped by the configured per-scan limit."""
    platform_accounts = [a for a in accounts if a.get("platform") == platform]
    candidates: list[tuple[dict[str, Any], Decision]] = []
    for account in platform_accounts:
        decision = evaluate_account(account, threshold, now)
        if decision is None:
            continue
        prev = account.get("rate_limit_reset_at")
        if prev is not None:
            prev_dt = _time(prev)
            if prev_dt is not None and prev_dt >= decision.reset_at:
                continue
        candidates.append((account, decision))
    limit = max(0, max_sleep_per_scan)
    candidates.sort(key=lambda item: (item[1].utilization_percent, item[1].reset_at), reverse=True)
    return candidates[:limit]


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _verify_sub2api_model() -> bool:
    url = os.getenv("VERIFY_API_URL", "").strip()
    api_key = os.getenv("VERIFY_API_KEY", "").strip()
    model = os.getenv("VERIFY_MODEL", "gpt-5.5").strip()
    if not url or not api_key:
        return True
    payload = json.dumps({"model": model, "messages": [{"role": "user", "content": "只回复 OK"}], "max_tokens": 20}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


async def _rollback_sleeps(account_ids: list[int]) -> None:
    if not account_ids:
        return
    async with repo.pool().acquire() as conn:
        await conn.execute(
            """
            UPDATE accounts
            SET rate_limited_at=NULL, rate_limit_reset_at=NULL, updated_at=NOW()
            WHERE id = ANY($1::bigint[])
            """,
            account_ids,
        )


def _production_scan_dependencies() -> ScanDependencies:
    return ScanDependencies(
        get_settings=repo.get_settings,
        list_oauth_accounts=repo.list_oauth_accounts,
        set_rate_limited=repo.set_rate_limited,
        insert_event=repo.insert_event,
        update_last_scan=repo.update_last_scan,
        rollback_sleeps=_rollback_sleeps,
        now=_now,
        refresh_scheduler=scheduler_refresh.refresh_scheduler_if_enabled,
        verify_model=_verify_sub2api_model,
        verify_after_sleep=lambda: _env_bool("VERIFY_AFTER_SLEEP", True),
    )


def _select_scan_candidates(
    accounts: list[dict[str, Any]],
    settings: Any,
    now: datetime,
) -> list[tuple[dict[str, Any], Decision]]:
    selected: list[tuple[dict[str, Any], Decision]] = []
    if settings.include_openai:
        selected.extend(
            select_sleep_candidates(accounts, settings.threshold_percent, now, "openai", settings.max_sleep_per_scan)
        )
    if settings.include_anthropic:
        selected.extend(
            select_sleep_candidates(accounts, settings.threshold_percent, now, "anthropic", settings.max_sleep_per_scan)
        )
    return selected


async def _apply_sleep_decisions(
    selected: list[tuple[dict[str, Any], Decision]],
    settings: Any,
    deps: ScanDependencies,
) -> tuple[list[int], list[SleeperEvent]]:
    events: list[SleeperEvent] = []
    updated_ids: list[int] = []
    for account, decision in selected:
        prev = account.get("rate_limit_reset_at")
        updated = await deps.set_rate_limited(account["id"], decision.reset_at)
        if not updated:
            continue
        updated_ids.append(account["id"])
        event = await deps.insert_event(
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
    return updated_ids, events


async def scan_once(force: bool = False) -> ScanResult:
    async with _scan_lock:
        return await scan_once_with_dependencies(force=force, deps=_production_scan_dependencies())


async def scan_once_with_dependencies(force: bool, deps: ScanDependencies) -> ScanResult:
    settings = await deps.get_settings()
    if not settings.enabled and not force:
        await deps.update_last_scan(0, 0)
        return ScanResult(scanned=0, triggered=0, events=[])

    accounts = await deps.list_oauth_accounts(settings.include_openai, settings.include_anthropic)
    selected = _select_scan_candidates(accounts, settings, deps.now())
    updated_ids, events = await _apply_sleep_decisions(selected, settings, deps)
    deps.refresh_scheduler()
    if updated_ids and deps.verify_after_sleep():
        if not deps.verify_model():
            await deps.rollback_sleeps(updated_ids)
            deps.refresh_scheduler()
            events = []

    await deps.update_last_scan(len(accounts), len(events))
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
