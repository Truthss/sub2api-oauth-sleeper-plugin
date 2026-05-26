from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.account_scope import AccountScanBatch, AccountScanScope, account_scope_from_settings, filter_whitelisted_accounts


@dataclass(frozen=True)
class FakeSettings:
    include_openai: bool = True
    include_anthropic: bool = True


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def account(account_id: int, platform: str = "openai") -> dict[str, Any]:
    return {"id": account_id, "platform": platform}


def test_account_scan_scope_platforms() -> None:
    assert_equal(AccountScanScope(True, True).platforms, ("openai", "anthropic"), "both platforms")
    assert_equal(AccountScanScope(True, False).platforms, ("openai",), "openai only")
    assert_equal(AccountScanScope(False, True).platforms, ("anthropic",), "anthropic only")
    assert_equal(AccountScanScope(False, False).platforms, (), "no platforms")


def test_account_scope_from_settings() -> None:
    scope = account_scope_from_settings(FakeSettings(include_openai=False, include_anthropic=True))

    assert_equal(scope.platforms, ("anthropic",), "settings-derived platforms")
    assert_equal(scope.is_empty, False, "settings-derived scope is not empty")


def test_filter_whitelisted_accounts_keeps_input_when_no_whitelist() -> None:
    accounts = [account(1), account(2)]

    assert_equal(filter_whitelisted_accounts(accounts, set()), accounts, "no whitelist keeps accounts")


def test_filter_whitelisted_accounts_skips_whitelisted_ids() -> None:
    accounts = [account(1), account(2), account(3)]

    assert_equal(filter_whitelisted_accounts(accounts, {1, 3}), [account(2)], "whitelist filtered")


def test_account_scan_batch_tracks_scanned_and_eligible_counts() -> None:
    batch = AccountScanBatch(scanned_count=3, eligible_accounts=[account(2)])

    assert_equal(batch.scanned_count, 3, "batch scanned count")
    assert_equal(batch.eligible_count, 1, "batch eligible count")


if __name__ == "__main__":
    tests = [
        test_account_scan_scope_platforms,
        test_account_scope_from_settings,
        test_filter_whitelisted_accounts_keeps_input_when_no_whitelist,
        test_filter_whitelisted_accounts_skips_whitelisted_ids,
        test_account_scan_batch_tracks_scanned_and_eligible_counts,
    ]
    for test in tests:
        try:
            test()
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            raise
        else:
            print(f"PASS {test.__name__}")
