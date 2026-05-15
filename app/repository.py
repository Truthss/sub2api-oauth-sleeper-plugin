from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .db import pool
from .schemas import SettingsOut, SettingsUpdate, SleeperEvent


def _f(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except Exception:
        return None


def _event_from_record(r: Any) -> SleeperEvent:
    return SleeperEvent(
        id=r.get("id"),
        account_id=r["account_id"],
        account_name=r.get("account_name"),
        platform=r["platform"],
        window_name=r["window_name"],
        utilization_percent=float(r["utilization_percent"]),
        threshold_percent=float(r["threshold_percent"]),
        reset_at=r["reset_at"],
        previous_rate_limit_reset_at=r.get("previous_rate_limit_reset_at"),
        created_at=r.get("created_at"),
    )


async def get_settings() -> SettingsOut:
    async with pool().acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM plugin_oauth_sleeper_settings WHERE id = 1")
    return SettingsOut(
        enabled=r["enabled"],
        threshold_percent=float(r["threshold_percent"]),
        scan_interval_seconds=r["scan_interval_seconds"],
        include_openai=r["include_openai"],
        include_anthropic=r["include_anthropic"],
        last_scan_at=r["last_scan_at"],
        last_scan_scanned=r["last_scan_scanned"],
        last_scan_triggered=r["last_scan_triggered"],
    )


async def update_settings(data: SettingsUpdate) -> SettingsOut:
    async with pool().acquire() as conn:
        await conn.execute(
            """
            UPDATE plugin_oauth_sleeper_settings
            SET enabled=$1,
                threshold_percent=$2,
                scan_interval_seconds=$3,
                include_openai=$4,
                include_anthropic=$5,
                updated_at=NOW()
            WHERE id=1
            """,
            data.enabled,
            data.threshold_percent,
            data.scan_interval_seconds,
            data.include_openai,
            data.include_anthropic,
        )
    return await get_settings()


async def update_last_scan(scanned: int, triggered: int) -> None:
    async with pool().acquire() as conn:
        await conn.execute(
            """
            UPDATE plugin_oauth_sleeper_settings
            SET last_scan_at=NOW(), last_scan_scanned=$1, last_scan_triggered=$2, updated_at=NOW()
            WHERE id=1
            """,
            scanned,
            triggered,
        )


async def list_oauth_accounts(include_openai: bool, include_anthropic: bool) -> list[dict[str, Any]]:
    platforms: list[str] = []
    if include_openai:
        platforms.append("openai")
    if include_anthropic:
        platforms.append("anthropic")
    if not platforms:
        return []
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, platform, type, status, extra, session_window_end, rate_limit_reset_at
            FROM accounts
            WHERE deleted_at IS NULL
              AND status = 'active'
              AND type = 'oauth'
              AND platform = ANY($1::text[])
            ORDER BY id
            """,
            platforms,
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        extra = r["extra"] or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        out.append({**dict(r), "extra": extra})
    return out


async def set_rate_limited(account_id: int, reset_at: datetime) -> bool:
    async with pool().acquire() as conn:
        tag = await conn.execute(
            """
            UPDATE accounts
            SET rate_limited_at = NOW(),
                rate_limit_reset_at = $1,
                updated_at = NOW()
            WHERE id = $2
              AND deleted_at IS NULL
              AND (rate_limit_reset_at IS NULL OR rate_limit_reset_at < $1)
            """,
            reset_at,
            account_id,
        )
    return tag.endswith(" 1")


async def insert_event(event: SleeperEvent) -> SleeperEvent:
    async with pool().acquire() as conn:
        r = await conn.fetchrow(
            """
            INSERT INTO plugin_oauth_sleeper_events (
                account_id, account_name, platform, window_name,
                utilization_percent, threshold_percent, reset_at, previous_rate_limit_reset_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            RETURNING *
            """,
            event.account_id,
            event.account_name,
            event.platform,
            event.window_name,
            event.utilization_percent,
            event.threshold_percent,
            event.reset_at,
            event.previous_rate_limit_reset_at,
        )
    return _event_from_record(r)


async def list_events(limit: int = 50) -> list[SleeperEvent]:
    limit = max(1, min(limit, 200))
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM plugin_oauth_sleeper_events ORDER BY created_at DESC LIMIT $1",
            limit,
        )
    return [_event_from_record(r) for r in rows]


async def list_sleeping_accounts() -> list[SleeperEvent]:
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (e.account_id)
                e.*
            FROM plugin_oauth_sleeper_events e
            JOIN accounts a ON a.id = e.account_id
            WHERE a.deleted_at IS NULL
              AND a.rate_limit_reset_at > NOW()
            ORDER BY e.account_id, e.created_at DESC
            LIMIT 200
            """
        )
    return [_event_from_record(r) for r in rows]
