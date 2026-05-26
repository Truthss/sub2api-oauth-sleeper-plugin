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

from fastapi import HTTPException

from app import main
from app.schemas import AccountPage, PageMeta, ScanResult, SettingsOut, SleeperEvent, SleeperEventPage


def assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_contains(text: str, expected: str, label: str) -> None:
    if expected not in text:
        raise AssertionError(f"{label}: expected to find {expected!r}")


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def settings_out() -> SettingsOut:
    return SettingsOut(
        enabled=True,
        threshold_percent=90,
        scan_interval_seconds=60,
        max_sleep_per_scan=3,
        include_openai=True,
        include_anthropic=True,
        last_scan_at=None,
        last_scan_scanned=0,
        last_scan_triggered=0,
    )


def event(account_id: int = 42) -> SleeperEvent:
    return SleeperEvent(
        id=1,
        account_id=account_id,
        account_name="codex",
        platform="openai",
        window_name="7d",
        utilization_percent=91,
        threshold_percent=90,
        reset_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
        previous_rate_limit_reset_at=None,
        created_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
    )


def test_add_whitelist_api_returns_status_when_manageable() -> None:
    original = main.repo.add_whitelist_account
    calls: list[int] = []

    async def fake_add(account_id: int) -> bool:
        calls.append(account_id)
        return True

    main.repo.add_whitelist_account = fake_add  # type: ignore[assignment]
    try:
        status = run(main.add_whitelist_api(42))
    finally:
        main.repo.add_whitelist_account = original  # type: ignore[assignment]

    assert_equal(calls, [42], "add whitelist call")
    assert_equal(status.account_id, 42, "status account id")
    assert_equal(status.is_whitelisted, True, "status flag")


def test_add_whitelist_api_raises_404_when_not_manageable() -> None:
    original = main.repo.add_whitelist_account

    async def fake_add(account_id: int) -> bool:
        return False

    main.repo.add_whitelist_account = fake_add  # type: ignore[assignment]
    try:
        try:
            run(main.add_whitelist_api(42))
        except HTTPException as exc:
            assert_equal(exc.status_code, 404, "not manageable status")
            assert_equal(exc.detail, "account is not in the current manageable OAuth scan scope", "detail")
        else:
            raise AssertionError("expected HTTPException")
    finally:
        main.repo.add_whitelist_account = original  # type: ignore[assignment]


def test_remove_whitelist_api_is_idempotent_status_response() -> None:
    original = main.repo.remove_whitelist_account
    calls: list[int] = []

    async def fake_remove(account_id: int) -> None:
        calls.append(account_id)

    main.repo.remove_whitelist_account = fake_remove  # type: ignore[assignment]
    try:
        status = run(main.remove_whitelist_api(42))
    finally:
        main.repo.remove_whitelist_account = original  # type: ignore[assignment]

    assert_equal(calls, [42], "remove whitelist call")
    assert_equal(status.account_id, 42, "status account id")
    assert_equal(status.is_whitelisted, False, "status flag")


def test_status_api_combines_settings_and_first_sleeping_page() -> None:
    original_get_settings = main.repo.get_settings
    original_list_sleeping = main.repo.list_sleeping_accounts_page

    async def fake_get_settings() -> SettingsOut:
        return settings_out()

    async def fake_list_sleeping_accounts_page(page: int = 1, page_size: int = 10) -> SleeperEventPage:
        assert_equal((page, page_size), (1, 10), "status sleeping page args")
        return SleeperEventPage(
            items=[event(42)],
            meta=PageMeta(total=5, page=1, page_size=10, total_pages=1),
        )

    main.repo.get_settings = fake_get_settings  # type: ignore[assignment]
    main.repo.list_sleeping_accounts_page = fake_list_sleeping_accounts_page  # type: ignore[assignment]
    try:
        status = run(main.status_api())
    finally:
        main.repo.get_settings = original_get_settings  # type: ignore[assignment]
        main.repo.list_sleeping_accounts_page = original_list_sleeping  # type: ignore[assignment]

    assert_equal(status.enabled, True, "status enabled")
    assert_equal(status.sleeping_count, 5, "sleeping total")
    assert_equal([item.account_id for item in status.sleeping_accounts], [42], "sleeping items")


def test_accounts_api_forwards_pagination_to_repository() -> None:
    original = main.repo.list_accounts_page
    calls: list[tuple[int, int]] = []

    async def fake_list_accounts_page(page: int = 1, page_size: int = 10) -> AccountPage:
        calls.append((page, page_size))
        return AccountPage(items=[], meta=PageMeta(total=0, page=page, page_size=page_size, total_pages=1))

    main.repo.list_accounts_page = fake_list_accounts_page  # type: ignore[assignment]
    try:
        page = run(main.accounts_api(page=2, page_size=5))
    finally:
        main.repo.list_accounts_page = original  # type: ignore[assignment]

    assert_equal(calls, [(2, 5)], "accounts pagination call")
    assert_equal(page.meta.page, 2, "accounts page")


def test_scan_once_api_forces_scan() -> None:
    original = main.scanner.scan_once
    calls: list[bool] = []

    async def fake_scan_once(force: bool = False) -> ScanResult:
        calls.append(force)
        return ScanResult(scanned=0, triggered=0, events=[])

    main.scanner.scan_once = fake_scan_once  # type: ignore[assignment]
    try:
        result = run(main.scan_once_api())
    finally:
        main.scanner.scan_once = original  # type: ignore[assignment]

    assert_equal(calls, [True], "scan force flag")
    assert_equal(result.scanned, 0, "scan result")


@dataclass(frozen=True)
class FakeRuntimeSettings:
    public_base_path_prefix: str = "/custom/oauth-sleeper"


def test_admin_page_sets_no_store_cache_header() -> None:
    original_get_settings = main.get_settings
    original_render_admin_html = main.render_admin_html
    calls: list[str] = []

    main.get_settings = lambda: FakeRuntimeSettings()  # type: ignore[assignment]

    def fake_render_admin_html(base_path: str) -> str:
        calls.append(base_path)
        return "<html>admin</html>"

    main.render_admin_html = fake_render_admin_html  # type: ignore[assignment]
    try:
        response = run(main.admin_page())
    finally:
        main.get_settings = original_get_settings  # type: ignore[assignment]
        main.render_admin_html = original_render_admin_html  # type: ignore[assignment]

    assert_equal(calls, ["/custom/oauth-sleeper"], "admin base path")
    assert_contains(response.headers["Cache-Control"], "no-store", "admin cache")


def test_security_headers_include_expected_headers_without_frame_ancestors() -> None:
    original_get_settings = main.get_settings
    main.get_settings = lambda: FakeRuntimeSettings(public_base_path_prefix="")  # type: ignore[assignment]

    async def fake_call_next(request: object) -> Any:
        from fastapi.responses import Response

        return Response("ok")

    try:
        response = run(main.security_headers(object(), fake_call_next))
    finally:
        main.get_settings = original_get_settings  # type: ignore[assignment]

    assert_equal(response.headers["X-Content-Type-Options"], "nosniff", "nosniff")
    assert_equal(response.headers["Referrer-Policy"], "strict-origin-when-cross-origin", "referrer policy")
    assert_equal("Content-Security-Policy" in response.headers, False, "no frame-ancestors header")


if __name__ == "__main__":
    tests = [
        test_add_whitelist_api_returns_status_when_manageable,
        test_add_whitelist_api_raises_404_when_not_manageable,
        test_remove_whitelist_api_is_idempotent_status_response,
        test_status_api_combines_settings_and_first_sleeping_page,
        test_accounts_api_forwards_pagination_to_repository,
        test_scan_once_api_forces_scan,
        test_admin_page_sets_no_store_cache_header,
        test_security_headers_include_expected_headers_without_frame_ancestors,
    ]
    for test in tests:
        try:
            test()
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            raise
        else:
            print(f"PASS {test.__name__}")
