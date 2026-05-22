from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.repository import scanner_platforms
from app.schemas import AccountOut, AccountPage, PageMeta, WhitelistStatus


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_account_out_exposes_whitelist_fields() -> None:
    reset_at = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    account = AccountOut(
        id=42,
        name="codex-oauth",
        platform="openai",
        status="active",
        type="oauth",
        rate_limit_reset_at=reset_at,
        is_whitelisted=True,
    )

    assert_equal(account.id, 42, "account id")
    assert_equal(account.name, "codex-oauth", "account name")
    assert_equal(account.platform, "openai", "account platform")
    assert_equal(account.status, "active", "account status")
    assert_equal(account.type, "oauth", "account type")
    assert_equal(account.rate_limit_reset_at, reset_at, "rate limit reset")
    assert_equal(account.is_whitelisted, True, "whitelist flag")


def test_account_page_wraps_items_and_meta() -> None:
    page = AccountPage(
        items=[],
        meta=PageMeta(total=0, page=1, page_size=10, total_pages=1),
    )

    assert_equal(page.items, [], "page items")
    assert_equal(page.meta.total, 0, "page total")
    assert_equal(page.meta.total_pages, 1, "page total pages")


def test_whitelist_status_shape() -> None:
    status = WhitelistStatus(account_id=42, is_whitelisted=False)

    assert_equal(status.account_id, 42, "status account id")
    assert_equal(status.is_whitelisted, False, "status whitelist flag")


def test_scanner_platforms_respects_settings_switches() -> None:
    assert_equal(scanner_platforms(True, True), ["openai", "anthropic"], "both platforms")
    assert_equal(scanner_platforms(True, False), ["openai"], "openai only")
    assert_equal(scanner_platforms(False, True), ["anthropic"], "anthropic only")
    assert_equal(scanner_platforms(False, False), [], "no platforms")


if __name__ == "__main__":
    tests = [
        test_account_out_exposes_whitelist_fields,
        test_account_page_wraps_items_and_meta,
        test_whitelist_status_shape,
        test_scanner_platforms_respects_settings_switches,
    ]
    for test in tests:
        try:
            test()
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            raise
        else:
            print(f"PASS {test.__name__}")
