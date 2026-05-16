from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import urllib.error
import urllib.request
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


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _refresh_sub2api_scheduler(group_id: int = 2, platform: str = "openai", modes: tuple[str, ...] = ("single",)) -> None:
    redis_host = os.getenv("SUB2API_REDIS_HOST", "redis")
    redis_port = _env_int("SUB2API_REDIS_PORT", 6379)

    def redis_command(*parts: str) -> str:
        payload = "*" + str(len(parts)) + "\r\n" + "".join(f"${len(p.encode())}\r\n{p}\r\n" for p in parts)
        with socket.create_connection((redis_host, redis_port), timeout=5) as sock:
            sock.sendall(payload.encode())
            sock.shutdown(socket.SHUT_WR)
            return sock.recv(1024 * 1024).decode(errors="replace")

    def parse_bulk(resp: str) -> str:
        if not resp.startswith("$"):
            return ""
        _, rest = resp.split("\r\n", 1)
        if rest.startswith("-1"):
            return ""
        return rest.split("\r\n", 1)[0]

    def parse_array(resp: str) -> list[str]:
        if not resp.startswith("*"):
            return []
        lines = resp.split("\r\n")
        out: list[str] = []
        i = 1
        while i < len(lines):
            if lines[i].startswith("$") and i + 1 < len(lines):
                out.append(lines[i + 1])
                i += 2
            else:
                i += 1
        return out

    keys_to_delete: list[str] = []
    for mode in modes:
        active_key = f"sched:active:{group_id}:{platform}:{mode}"
        ver = parse_bulk(redis_command("GET", active_key))
        keys_to_delete.extend([
            active_key,
            f"sched:ready:{group_id}:{platform}:{mode}",
            f"sched:ver:{group_id}:{platform}:{mode}",
            f"sched:lock:{group_id}:{platform}:{mode}",
        ])
        if ver:
            keys_to_delete.append(f"sched:{group_id}:{platform}:{mode}:v{ver}")
    cursor = "0"
    pattern = f"sticky_session:{group_id}:{platform}:*"
    while True:
        resp = redis_command("SCAN", cursor, "MATCH", pattern, "COUNT", "100")
        arr = parse_array(resp)
        if not arr:
            break
        cursor = arr[0]
        keys_to_delete.extend(arr[1:])
        if cursor == "0":
            break
    if keys_to_delete:
        redis_command("DEL", *keys_to_delete)


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


async def scan_once(force: bool = False) -> ScanResult:
    async with _scan_lock:
        settings = await repo.get_settings()
        if not settings.enabled and not force:
            await repo.update_last_scan(0, 0)
            return ScanResult(scanned=0, triggered=0, events=[])
        accounts = await repo.list_oauth_accounts(settings.include_openai, settings.include_anthropic)
        now = _now()
        max_sleep_per_scan = settings.max_sleep_per_scan
        selected: list[tuple[dict[str, Any], Decision]] = []
        if settings.include_openai:
            selected.extend(
                select_sleep_candidates(
                    accounts,
                    settings.threshold_percent,
                    now,
                    "openai",
                    max_sleep_per_scan,
                )
            )
        if settings.include_anthropic:
            selected.extend(
                select_sleep_candidates(
                    accounts,
                    settings.threshold_percent,
                    now,
                    "anthropic",
                    max_sleep_per_scan,
                )
            )
        events: list[SleeperEvent] = []
        updated_ids: list[int] = []
        for account, decision in selected:
            prev = account.get("rate_limit_reset_at")
            updated = await repo.set_rate_limited(account["id"], decision.reset_at)
            if not updated:
                continue
            updated_ids.append(account["id"])
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
        should_refresh = _env_bool("REFRESH_SUB2API_SCHEDULER", True)
        group_id = _env_int("SUB2API_OPENAI_GROUP_ID", 2)
        if should_refresh:
            _refresh_sub2api_scheduler(group_id=group_id, platform="openai", modes=("single",))
        if updated_ids and _env_bool("VERIFY_AFTER_SLEEP", True):
            if not _verify_sub2api_model():
                await _rollback_sleeps(updated_ids)
                if should_refresh:
                    _refresh_sub2api_scheduler(group_id=group_id, platform="openai", modes=("single",))
                events = []
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
