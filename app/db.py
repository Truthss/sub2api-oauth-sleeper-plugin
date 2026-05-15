from __future__ import annotations

import asyncpg
from pathlib import Path

from .config import Settings

_pool: asyncpg.Pool | None = None


async def init_db(settings: Settings) -> None:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
    migration_path = Path(__file__).resolve().parent.parent / "migrations" / "001_init.sql"
    sql = migration_path.read_text(encoding="utf-8")
    async with pool().acquire() as conn:
        await conn.execute(sql)
        await conn.execute(
            """
            UPDATE plugin_oauth_sleeper_settings
            SET threshold_percent=$1,
                scan_interval_seconds=$2,
                include_openai=$3,
                include_anthropic=$4,
                updated_at=NOW()
            WHERE id=1
              AND last_scan_at IS NULL
              AND last_scan_scanned = 0
              AND last_scan_triggered = 0
            """,
            settings.default_sleep_threshold_percent,
            settings.scan_interval_seconds,
            settings.include_openai,
            settings.include_anthropic,
        )


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("database pool not initialized")
    return _pool


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
