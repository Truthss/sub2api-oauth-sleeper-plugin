from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import repository as repo


def assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_contains(text: str, expected: str, label: str) -> None:
    if expected not in text:
        raise AssertionError(f"{label}: expected to find {expected!r}")


@dataclass(frozen=True)
class FakeSettings:
    include_openai: bool = True
    include_anthropic: bool = True


class FakeRow(dict):
    def get(self, key: str, default: Any = None) -> Any:
        return super().get(key, default)


class FakeAcquire:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn

    async def __aenter__(self) -> "FakeConn":
        self.conn.entered += 1
        return self.conn

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.conn.exited += 1


class FakePool:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.conn)


class FakeConn:
    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0
        self.fetch_rows: list[Any] = []
        self.fetchval_values: list[Any] = []
        self.execute_result = "UPDATE 1"
        self.fetch_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchval_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        self.fetch_calls.append((sql, args))
        return self.fetch_rows

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.fetchval_calls.append((sql, args))
        if self.fetchval_values:
            return self.fetchval_values.pop(0)
        return None

    async def execute(self, sql: str, *args: Any) -> str:
        self.execute_calls.append((sql, args))
        return self.execute_result


def patch_pool(conn: FakeConn) -> Any:
    original = repo.pool
    repo.pool = lambda: FakePool(conn)  # type: ignore[assignment]
    return original


def restore_pool(original: Any) -> None:
    repo.pool = original  # type: ignore[assignment]


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_scanner_platforms_respects_disabled_platforms() -> None:
    assert_equal(repo.scanner_platforms(False, False), [], "no platforms")
    assert_equal(repo.scanner_platforms(True, False), ["openai"], "openai only")
    assert_equal(repo.scanner_platforms(False, True), ["anthropic"], "anthropic only")
    assert_equal(repo.scanner_platforms(True, True), ["openai", "anthropic"], "both platforms")


def test_list_oauth_accounts_returns_empty_without_query_when_no_platforms() -> None:
    conn = FakeConn()
    original = patch_pool(conn)
    try:
        accounts = run(repo.list_oauth_accounts(False, False))
    finally:
        restore_pool(original)

    assert_equal(accounts, [], "empty platform accounts")
    assert_equal(conn.fetch_calls, [], "no query when platform scope is empty")


def test_list_oauth_accounts_decodes_extra_json_string() -> None:
    conn = FakeConn()
    conn.fetch_rows = [
        FakeRow(
            id=1,
            name="codex",
            platform="openai",
            type="oauth",
            status="active",
            extra='{"codex_7d_used_percent": 91}',
            session_window_end=None,
            rate_limit_reset_at=None,
        )
    ]
    original = patch_pool(conn)
    try:
        accounts = run(repo.list_oauth_accounts(True, False))
    finally:
        restore_pool(original)

    assert_equal(accounts[0]["extra"], {"codex_7d_used_percent": 91}, "decoded extra")
    assert_contains(conn.fetch_calls[0][0], "deleted_at IS NULL", "active account filter")
    assert_contains(conn.fetch_calls[0][0], "type = 'oauth'", "oauth filter")
    assert_contains(conn.fetch_calls[0][0], "platform = ANY", "platform filter")


def test_list_oauth_accounts_uses_empty_extra_for_invalid_json() -> None:
    conn = FakeConn()
    conn.fetch_rows = [
        FakeRow(
            id=1,
            name="bad-json",
            platform="openai",
            type="oauth",
            status="active",
            extra="{bad-json",
            session_window_end=None,
            rate_limit_reset_at=None,
        )
    ]
    original = patch_pool(conn)
    try:
        accounts = run(repo.list_oauth_accounts(True, False))
    finally:
        restore_pool(original)

    assert_equal(accounts[0]["extra"], {}, "invalid json extra")


def test_list_accounts_page_clamps_page_and_page_size() -> None:
    conn = FakeConn()
    conn.fetchval_values = [0]
    original_pool = patch_pool(conn)
    original_get_settings = repo.get_settings
    repo.get_settings = lambda: asyncio.sleep(0, FakeSettings())  # type: ignore[assignment]
    try:
        page = run(repo.list_accounts_page(page=0, page_size=999))
    finally:
        repo.get_settings = original_get_settings  # type: ignore[assignment]
        restore_pool(original_pool)

    assert_equal(page.meta.page, 1, "clamped page")
    assert_equal(page.meta.page_size, 10, "clamped page size")
    assert_equal(conn.fetch_calls[0][1][-2:], (10, 0), "limit and offset")


def test_list_accounts_page_marks_whitelisted_accounts() -> None:
    conn = FakeConn()
    conn.fetchval_values = [2]
    conn.fetch_rows = [
        FakeRow(
            id=1,
            name="managed",
            platform="openai",
            status="active",
            type="oauth",
            rate_limit_reset_at=None,
            is_whitelisted=False,
        ),
        FakeRow(
            id=2,
            name="skip",
            platform="openai",
            status="active",
            type="oauth",
            rate_limit_reset_at=None,
            is_whitelisted=True,
        ),
    ]
    original_pool = patch_pool(conn)
    original_get_settings = repo.get_settings
    repo.get_settings = lambda: asyncio.sleep(0, FakeSettings())  # type: ignore[assignment]
    try:
        page = run(repo.list_accounts_page(page=1, page_size=10))
    finally:
        repo.get_settings = original_get_settings  # type: ignore[assignment]
        restore_pool(original_pool)

    assert_equal([item.is_whitelisted for item in page.items], [False, True], "whitelist flags")
    assert_contains(conn.fetch_calls[0][0], "LEFT JOIN plugin_oauth_sleeper_whitelist", "whitelist join")


def test_account_is_manageable_returns_false_when_platform_scope_empty() -> None:
    conn = FakeConn()
    original_pool = patch_pool(conn)
    original_get_settings = repo.get_settings
    repo.get_settings = lambda: asyncio.sleep(0, FakeSettings(False, False))  # type: ignore[assignment]
    try:
        manageable = run(repo.account_is_manageable(42))
    finally:
        repo.get_settings = original_get_settings  # type: ignore[assignment]
        restore_pool(original_pool)

    assert_equal(manageable, False, "not manageable")
    assert_equal(conn.fetchval_calls, [], "no query when platform scope is empty")


def test_add_whitelist_account_returns_false_for_unmanageable_account() -> None:
    conn = FakeConn()
    original_pool = patch_pool(conn)
    original_account_is_manageable = repo.account_is_manageable
    repo.account_is_manageable = lambda account_id: asyncio.sleep(0, False)  # type: ignore[assignment]
    try:
        ok = run(repo.add_whitelist_account(42))
    finally:
        repo.account_is_manageable = original_account_is_manageable  # type: ignore[assignment]
        restore_pool(original_pool)

    assert_equal(ok, False, "unmanageable whitelist add")
    assert_equal(conn.execute_calls, [], "no insert for unmanageable account")


def test_set_rate_limited_returns_true_only_on_update_one() -> None:
    reset_at = datetime(2026, 5, 18, tzinfo=timezone.utc)
    conn = FakeConn()
    original = patch_pool(conn)
    try:
        conn.execute_result = "UPDATE 1"
        updated = run(repo.set_rate_limited(42, reset_at))
        conn.execute_result = "UPDATE 0"
        skipped = run(repo.set_rate_limited(42, reset_at))
    finally:
        restore_pool(original)

    assert_equal(updated, True, "updated row")
    assert_equal(skipped, False, "skipped row")


def test_set_rate_limited_sql_keeps_conservative_guard() -> None:
    reset_at = datetime(2026, 5, 18, tzinfo=timezone.utc)
    conn = FakeConn()
    original = patch_pool(conn)
    try:
        run(repo.set_rate_limited(42, reset_at))
    finally:
        restore_pool(original)

    sql = conn.execute_calls[0][0]
    assert_contains(sql, "deleted_at IS NULL", "deleted guard")
    assert_contains(sql, "rate_limit_reset_at IS NULL OR rate_limit_reset_at < $1", "conservative reset guard")


def test_list_sleeping_accounts_page_returns_latest_event_per_account_ordered_by_reset() -> None:
    reset_at = datetime(2026, 5, 18, tzinfo=timezone.utc)
    created_at = datetime(2026, 5, 16, tzinfo=timezone.utc)
    conn = FakeConn()
    conn.fetchval_values = [1]
    conn.fetch_rows = [
        FakeRow(
            id=7,
            account_id=42,
            account_name="codex",
            platform="openai",
            window_name="7d",
            utilization_percent=91,
            threshold_percent=90,
            reset_at=reset_at,
            previous_rate_limit_reset_at=None,
            created_at=created_at,
        )
    ]
    original = patch_pool(conn)
    try:
        page = run(repo.list_sleeping_accounts_page(page=1, page_size=10))
    finally:
        restore_pool(original)

    assert_equal(page.meta.total, 1, "sleeping total")
    assert_equal(page.items[0].account_id, 42, "sleeping account id")
    sql = conn.fetch_calls[0][0]
    assert_contains(sql, "DISTINCT ON (e.account_id)", "latest event per account")
    assert_contains(sql, "a.rate_limit_reset_at > NOW()", "currently sleeping filter")
    assert_contains(sql, "ORDER BY reset_at ASC", "reset ordering")


if __name__ == "__main__":
    tests = [
        test_scanner_platforms_respects_disabled_platforms,
        test_list_oauth_accounts_returns_empty_without_query_when_no_platforms,
        test_list_oauth_accounts_decodes_extra_json_string,
        test_list_oauth_accounts_uses_empty_extra_for_invalid_json,
        test_list_accounts_page_clamps_page_and_page_size,
        test_list_accounts_page_marks_whitelisted_accounts,
        test_account_is_manageable_returns_false_when_platform_scope_empty,
        test_add_whitelist_account_returns_false_for_unmanageable_account,
        test_set_rate_limited_returns_true_only_on_update_one,
        test_set_rate_limited_sql_keeps_conservative_guard,
        test_list_sleeping_accounts_page_returns_latest_event_per_account_ordered_by_reset,
    ]
    for test in tests:
        try:
            test()
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            raise
        else:
            print(f"PASS {test.__name__}")
