from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .db import pool
from .schemas import AccountOut, AccountPage, PageMeta, SettingsOut, SettingsUpdate, SleeperEvent, SleeperEventPage


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


def scanner_platforms(include_openai: bool, include_anthropic: bool) -> list[str]:
    platforms: list[str] = []
    if include_openai:
        platforms.append("openai")
    if include_anthropic:
        platforms.append("anthropic")
    return platforms


async def get_settings() -> SettingsOut:
    async with pool().acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM plugin_oauth_sleeper_settings WHERE id = 1")
    return SettingsOut(
        enabled=r["enabled"],
        threshold_percent=float(r["threshold_percent"]),
        scan_interval_seconds=r["scan_interval_seconds"],
        max_sleep_per_scan=r["max_sleep_per_scan"],
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
                max_sleep_per_scan=$4,
                include_openai=$5,
                include_anthropic=$6,
                updated_at=NOW()
            WHERE id=1
            """,
            data.enabled,
            data.threshold_percent,
            data.scan_interval_seconds,
            data.max_sleep_per_scan,
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
    platforms = scanner_platforms(include_openai, include_anthropic)
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


def _account_from_record(r: Any) -> AccountOut:
    return AccountOut(
        id=r["id"],
        name=r.get("name"),
        platform=r["platform"],
        status=r["status"],
        type=r["type"],
        rate_limit_reset_at=r.get("rate_limit_reset_at"),
        is_whitelisted=bool(r.get("is_whitelisted")),
    )


async def list_accounts_page(page: int = 1, page_size: int = 10) -> AccountPage:
    settings = await get_settings()
    platforms = scanner_platforms(settings.include_openai, settings.include_anthropic)
    page = max(1, page)
    page_size = max(1, min(page_size, 10))
    if not platforms:
        return AccountPage(items=[], meta=_page_meta(0, page, page_size))

    offset = (page - 1) * page_size
    async with pool().acquire() as conn:
        total = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM accounts
            WHERE deleted_at IS NULL
              AND status = 'active'
              AND type = 'oauth'
              AND platform = ANY($1::text[])
            """,
            platforms,
        )
        rows = await conn.fetch(
            """
            SELECT
                a.id,
                a.name,
                a.platform,
                a.status,
                a.type,
                a.rate_limit_reset_at,
                (w.account_id IS NOT NULL) AS is_whitelisted
            FROM accounts a
            LEFT JOIN plugin_oauth_sleeper_whitelist w ON w.account_id = a.id
            WHERE a.deleted_at IS NULL
              AND a.status = 'active'
              AND a.type = 'oauth'
              AND a.platform = ANY($1::text[])
            ORDER BY a.id
            LIMIT $2 OFFSET $3
            """,
            platforms,
            page_size,
            offset,
        )
    return AccountPage(
        items=[_account_from_record(r) for r in rows],
        meta=_page_meta(int(total or 0), page, page_size),
    )


async def account_is_manageable(account_id: int) -> bool:
    settings = await get_settings()
    platforms = scanner_platforms(settings.include_openai, settings.include_anthropic)
    if not platforms:
        return False
    async with pool().acquire() as conn:
        found = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM accounts
                WHERE id = $1
                  AND deleted_at IS NULL
                  AND status = 'active'
                  AND type = 'oauth'
                  AND platform = ANY($2::text[])
            )
            """,
            account_id,
            platforms,
        )
    return bool(found)


async def add_whitelist_account(account_id: int) -> bool:
    if not await account_is_manageable(account_id):
        return False
    async with pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO plugin_oauth_sleeper_whitelist (account_id)
            VALUES ($1)
            ON CONFLICT (account_id) DO NOTHING
            """,
            account_id,
        )
    return True


async def remove_whitelist_account(account_id: int) -> None:
    async with pool().acquire() as conn:
        await conn.execute(
            "DELETE FROM plugin_oauth_sleeper_whitelist WHERE account_id = $1",
            account_id,
        )


async def list_whitelisted_account_ids() -> set[int]:
    async with pool().acquire() as conn:
        rows = await conn.fetch("SELECT account_id FROM plugin_oauth_sleeper_whitelist")
    return {int(r["account_id"]) for r in rows}


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


def _page_meta(total: int, page: int, page_size: int) -> PageMeta:
    total_pages = max(1, (total + page_size - 1) // page_size)
    return PageMeta(total=total, page=page, page_size=page_size, total_pages=total_pages)


async def list_events_page(page: int = 1, page_size: int = 10) -> SleeperEventPage:
    page = max(1, page)
    page_size = max(1, min(page_size, 10))
    offset = (page - 1) * page_size
    async with pool().acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM plugin_oauth_sleeper_events")
        rows = await conn.fetch(
            """
            SELECT *
            FROM plugin_oauth_sleeper_events
            ORDER BY created_at DESC, id DESC
            LIMIT $1 OFFSET $2
            """,
            page_size,
            offset,
        )
    return SleeperEventPage(items=[_event_from_record(r) for r in rows], meta=_page_meta(int(total or 0), page, page_size))


async def count_sleeping_accounts() -> int:
    async with pool().acquire() as conn:
        total = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM (
                SELECT DISTINCT e.account_id
                FROM plugin_oauth_sleeper_events e
                JOIN accounts a ON a.id = e.account_id
                WHERE a.deleted_at IS NULL
                  AND a.rate_limit_reset_at > NOW()
            ) s
            """
        )
    return int(total or 0)


async def list_sleeping_accounts_page(page: int = 1, page_size: int = 10) -> SleeperEventPage:
    page = max(1, page)
    page_size = max(1, min(page_size, 10))
    offset = (page - 1) * page_size
    async with pool().acquire() as conn:
        total = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM (
                SELECT DISTINCT e.account_id
                FROM plugin_oauth_sleeper_events e
                JOIN accounts a ON a.id = e.account_id
                WHERE a.deleted_at IS NULL
                  AND a.rate_limit_reset_at > NOW()
            ) s
            """
        )
        rows = await conn.fetch(
            """
            SELECT *
            FROM (
                SELECT DISTINCT ON (e.account_id)
                    e.*
                FROM plugin_oauth_sleeper_events e
                JOIN accounts a ON a.id = e.account_id
                WHERE a.deleted_at IS NULL
                  AND a.rate_limit_reset_at > NOW()
                ORDER BY e.account_id, e.created_at DESC, e.id DESC
            ) latest
            ORDER BY reset_at ASC, created_at DESC, id DESC
            LIMIT $1 OFFSET $2
            """,
            page_size,
            offset,
        )
    return SleeperEventPage(items=[_event_from_record(r) for r in rows], meta=_page_meta(int(total or 0), page, page_size))


async def list_sleeping_accounts() -> list[SleeperEvent]:
    return (await list_sleeping_accounts_page(page=1, page_size=10)).items
