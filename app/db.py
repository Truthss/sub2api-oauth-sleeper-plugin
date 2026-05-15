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
            INSERT INTO plugin_oauth_sleeper_settings (
                id, threshold_percent, scan_interval_seconds, include_openai, include_anthropic
            ) VALUES (1, $1, $2, $3, $4)
            ON CONFLICT (id) DO NOTHING
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
