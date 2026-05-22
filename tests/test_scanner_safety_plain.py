import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import scanner
from app.schemas import SleeperEvent


@dataclass
class FakeSettings:
    enabled: bool = True
    include_openai: bool = True
    include_anthropic: bool = False
    threshold_percent: float = 90
    max_sleep_per_scan: int = 3


class FakeScanStore:
    def __init__(
        self,
        settings: FakeSettings,
        accounts: list[dict[str, Any]],
        whitelisted_ids: set[int] | None = None,
    ) -> None:
        self.settings = settings
        self.accounts = accounts
        self.whitelisted_ids = whitelisted_ids or set()
        self.updated_ids: list[int] = []
        self.inserted_events: list[SleeperEvent] = []
        self.last_scan_calls: list[tuple[int, int]] = []
        self.rollback_calls: list[list[int]] = []

    async def get_settings(self) -> FakeSettings:
        return self.settings

    async def list_oauth_accounts(self, include_openai: bool, include_anthropic: bool) -> list[dict[str, Any]]:
        return self.accounts

    async def list_whitelisted_account_ids(self) -> set[int]:
        return self.whitelisted_ids

    async def set_rate_limited(self, account_id: int, reset_at: datetime) -> bool:
        self.updated_ids.append(account_id)
        return True

    async def insert_event(self, event: SleeperEvent) -> SleeperEvent:
        self.inserted_events.append(event)
        return event

    async def update_last_scan(self, scanned: int, triggered: int) -> None:
        self.last_scan_calls.append((scanned, triggered))

    async def rollback_sleeps(self, account_ids: list[int]) -> None:
        self.rollback_calls.append(account_ids)


def account(account_id: int, percent: float, reset_at: str = "2026-05-21T22:00:00+00:00") -> dict[str, Any]:
    return {
        "id": account_id,
        "name": f"acct-{account_id}",
        "platform": "openai",
        "rate_limit_reset_at": None,
        "extra": {
            "codex_7d_used_percent": percent,
            "codex_7d_reset_at": reset_at,
        },
    }


def dependencies(
    store: FakeScanStore,
    *,
    refresh_result: bool = True,
    verify_result: bool = True,
) -> scanner.ScanDependencies:
    refresh_calls: list[bool] = []

    def refresh_scheduler() -> bool:
        refresh_calls.append(refresh_result)
        return refresh_result

    deps = scanner.ScanDependencies(
        get_settings=store.get_settings,
        list_oauth_accounts=store.list_oauth_accounts,
        list_whitelisted_account_ids=store.list_whitelisted_account_ids,
        set_rate_limited=store.set_rate_limited,
        insert_event=store.insert_event,
        update_last_scan=store.update_last_scan,
        rollback_sleeps=store.rollback_sleeps,
        now=lambda: datetime(2026, 5, 16, tzinfo=timezone.utc),
        refresh_scheduler=refresh_scheduler,
        verify_model=lambda: verify_result,
        verify_after_sleep=lambda: True,
    )
    deps.refresh_calls = refresh_calls  # type: ignore[attr-defined]
    return deps


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_respects_max_per_scan_without_min_remaining_floor() -> None:
    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    accounts = [account(1, 100), account(2, 99), account(3, 98), account(4, 10), account(5, 5)]
    selected = scanner.select_sleep_candidates(accounts, 90, now, "openai", 3)
    assert_equal([a["id"] for a, _ in selected], [1, 2, 3], "max per scan selection")
    assert_equal(selected[0][1].window_name, "7d", "decision window")


def test_zero_max_per_scan_disables_sleeping() -> None:
    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    selected = scanner.select_sleep_candidates([account(1, 100), account(2, 99), account(3, 10)], 90, now, "openai", 0)
    assert_equal(selected, [], "zero max per scan")


def test_orders_by_highest_utilization_first() -> None:
    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    accounts = [account(1, 91), account(2, 100), account(3, 95), account(4, 1), account(5, 1)]
    selected = scanner.select_sleep_candidates(accounts, 90, now, "openai", 2)
    assert_equal([a["id"] for a, _ in selected], [2, 3], "utilization ordering")


def test_scan_once_with_dependencies_returns_zero_when_disabled_without_force() -> None:
    store = FakeScanStore(FakeSettings(enabled=False), [account(1, 100)])
    deps = dependencies(store)

    result = asyncio.run(scanner.scan_once_with_dependencies(force=False, deps=deps))

    assert_equal(result.scanned, 0, "disabled scanned count")
    assert_equal(result.triggered, 0, "disabled triggered count")
    assert_equal(store.last_scan_calls, [(0, 0)], "disabled last scan call")


def test_scan_once_with_dependencies_ignores_scheduler_refresh_failure() -> None:
    store = FakeScanStore(FakeSettings(), [])
    deps = dependencies(store, refresh_result=False)

    result = asyncio.run(scanner.scan_once_with_dependencies(force=True, deps=deps))

    assert_equal(result.scanned, 0, "empty scanned count")
    assert_equal(result.triggered, 0, "empty triggered count")
    assert_equal(store.last_scan_calls, [(0, 0)], "empty last scan call")
    assert_equal(deps.refresh_calls, [False], "refresh attempted once")  # type: ignore[attr-defined]


def test_scan_once_with_dependencies_skips_whitelisted_accounts() -> None:
    store = FakeScanStore(
        FakeSettings(),
        [account(1, 100), account(2, 99)],
        whitelisted_ids={1},
    )
    deps = dependencies(store)

    result = asyncio.run(scanner.scan_once_with_dependencies(force=True, deps=deps))

    assert_equal(result.scanned, 2, "scanned includes whitelisted accounts")
    assert_equal(result.triggered, 1, "trigger excludes whitelisted accounts")
    assert_equal(store.updated_ids, [2], "only non-whitelisted account slept")


def test_scan_once_with_dependencies_rolls_back_when_verify_fails() -> None:
    store = FakeScanStore(FakeSettings(), [account(1, 100)])
    deps = dependencies(store, refresh_result=True, verify_result=False)

    result = asyncio.run(scanner.scan_once_with_dependencies(force=True, deps=deps))

    assert_equal(result.scanned, 1, "verify failure scanned count")
    assert_equal(result.triggered, 0, "verify failure triggered count")
    assert_equal(store.updated_ids, [1], "rate-limited account")
    assert_equal(store.rollback_calls, [[1]], "rollback ids")
    assert_equal(store.last_scan_calls, [(1, 0)], "verify failure last scan call")
    assert_equal(deps.refresh_calls, [True, True], "refresh before and after rollback")  # type: ignore[attr-defined]


if __name__ == "__main__":
    tests = [
        test_respects_max_per_scan_without_min_remaining_floor,
        test_zero_max_per_scan_disables_sleeping,
        test_orders_by_highest_utilization_first,
        test_scan_once_with_dependencies_returns_zero_when_disabled_without_force,
        test_scan_once_with_dependencies_ignores_scheduler_refresh_failure,
        test_scan_once_with_dependencies_skips_whitelisted_accounts,
        test_scan_once_with_dependencies_rolls_back_when_verify_fails,
    ]
    for test in tests:
        try:
            test()
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            raise
        else:
            print(f"PASS {test.__name__}")
