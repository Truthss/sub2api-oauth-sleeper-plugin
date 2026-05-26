from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import scanner


def assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_is_none(actual: Any, label: str) -> None:
    if actual is not None:
        raise AssertionError(f"{label}: expected None, got {actual!r}")


def assert_is_not_none(actual: Any, label: str) -> None:
    if actual is None:
        raise AssertionError(f"{label}: expected a value, got None")


def utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def openai_account(
    account_id: int,
    *,
    p5: Any = None,
    r5: Any = None,
    p7: Any = None,
    r7: Any = None,
    prev_reset: Any = None,
) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if p5 is not None:
        extra["codex_5h_used_percent"] = p5
    if r5 is not None:
        extra["codex_5h_reset_at"] = r5
    if p7 is not None:
        extra["codex_7d_used_percent"] = p7
    if r7 is not None:
        extra["codex_7d_reset_at"] = r7
    return {
        "id": account_id,
        "name": f"openai-{account_id}",
        "platform": "openai",
        "extra": extra,
        "rate_limit_reset_at": prev_reset,
    }


def anthropic_account(
    account_id: int,
    *,
    p5: Any = None,
    r5: Any = None,
    p7: Any = None,
    r7: Any = None,
) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if p5 is not None:
        extra["session_window_utilization"] = p5
    if p7 is not None:
        extra["passive_usage_7d_utilization"] = p7
    if r7 is not None:
        extra["passive_usage_7d_reset"] = r7
    return {
        "id": account_id,
        "name": f"anthropic-{account_id}",
        "platform": "anthropic",
        "session_window_end": r5,
        "extra": extra,
        "rate_limit_reset_at": None,
    }


@dataclass(frozen=True)
class FakeSettings:
    threshold_percent: float = 90
    max_sleep_per_scan: int = 2
    include_openai: bool = True
    include_anthropic: bool = True


def test_evaluate_openai_chooses_later_reset_window_when_both_hit() -> None:
    now = utc(2026, 5, 16)
    account = openai_account(
        1,
        p5=95,
        r5="2026-05-16T05:00:00+00:00",
        p7=91,
        r7="2026-05-23T00:00:00+00:00",
    )

    decision = scanner.evaluate_openai(account, threshold=90, now=now)

    assert_is_not_none(decision, "openai decision")
    assert_equal(decision.window_name, "7d", "openai later window")
    assert_equal(decision.utilization_percent, 91.0, "openai utilization")
    assert_equal(decision.reset_at, utc(2026, 5, 23), "openai reset")


def test_evaluate_openai_ignores_expired_reset_window() -> None:
    now = utc(2026, 5, 16)
    account = openai_account(1, p5=100, r5="2026-05-15T23:59:59+00:00")

    decision = scanner.evaluate_openai(account, threshold=90, now=now)

    assert_is_none(decision, "expired openai window")


def test_evaluate_openai_accepts_iso_seconds_and_milliseconds_reset_times() -> None:
    now = utc(2026, 5, 16)
    iso_decision = scanner.evaluate_openai(
        openai_account(1, p5=91, r5="2026-05-16T01:00:00Z"),
        threshold=90,
        now=now,
    )
    seconds_decision = scanner.evaluate_openai(
        openai_account(2, p5=91, r5=1780000000),
        threshold=90,
        now=now,
    )
    millis_decision = scanner.evaluate_openai(
        openai_account(3, p5=91, r5=1780000000000),
        threshold=90,
        now=now,
    )

    assert_is_not_none(iso_decision, "iso reset decision")
    assert_equal(iso_decision.reset_at, utc(2026, 5, 16, 1), "iso reset")
    assert_is_not_none(seconds_decision, "seconds reset decision")
    assert_is_not_none(millis_decision, "milliseconds reset decision")
    assert_equal(seconds_decision.reset_at, millis_decision.reset_at, "epoch unit normalization")


def test_evaluate_anthropic_multiplies_fraction_utilization_by_100() -> None:
    now = utc(2026, 5, 16)
    account = anthropic_account(10, p5=0.91, r5="2026-05-16T04:00:00+00:00")

    decision = scanner.evaluate_anthropic(account, threshold=90, now=now)

    assert_is_not_none(decision, "anthropic decision")
    assert_equal(decision.window_name, "5h", "anthropic window")
    assert_equal(decision.utilization_percent, 91.0, "anthropic percent conversion")


def test_evaluate_anthropic_chooses_later_7d_reset_when_both_windows_hit() -> None:
    now = utc(2026, 5, 16)
    account = anthropic_account(
        10,
        p5=0.99,
        r5="2026-05-16T04:00:00+00:00",
        p7=0.92,
        r7="2026-05-23T00:00:00+00:00",
    )

    decision = scanner.evaluate_anthropic(account, threshold=90, now=now)

    assert_is_not_none(decision, "anthropic decision")
    assert_equal(decision.window_name, "7d", "anthropic later window")
    assert_equal(decision.utilization_percent, 92.0, "anthropic 7d percent")
    assert_equal(decision.reset_at, utc(2026, 5, 23), "anthropic reset")


def test_select_sleep_candidates_skips_accounts_with_existing_later_reset() -> None:
    now = utc(2026, 5, 16)
    acct = openai_account(
        1,
        p5=100,
        r5="2026-05-17T00:00:00+00:00",
        prev_reset="2026-05-18T00:00:00+00:00",
    )

    selected = scanner.select_sleep_candidates([acct], 90, now, "openai", 3)

    assert_equal(selected, [], "existing later reset skips account")


def test_select_sleep_candidates_allows_existing_earlier_reset_to_extend_sleep() -> None:
    now = utc(2026, 5, 16)
    acct = openai_account(
        1,
        p5=100,
        r5="2026-05-18T00:00:00+00:00",
        prev_reset="2026-05-17T00:00:00+00:00",
    )

    selected = scanner.select_sleep_candidates([acct], 90, now, "openai", 3)

    assert_equal([item[0]["id"] for item in selected], [1], "existing earlier reset can extend")


def test_select_scan_candidates_applies_max_sleep_per_scan_per_platform() -> None:
    now = utc(2026, 5, 16)
    accounts = [
        openai_account(1, p5=100, r5="2026-05-17T00:00:00+00:00"),
        openai_account(2, p5=99, r5="2026-05-17T00:00:00+00:00"),
        openai_account(3, p5=98, r5="2026-05-17T00:00:00+00:00"),
        anthropic_account(11, p5=1.0, r5="2026-05-17T00:00:00+00:00"),
        anthropic_account(12, p5=0.99, r5="2026-05-17T00:00:00+00:00"),
        anthropic_account(13, p5=0.98, r5="2026-05-17T00:00:00+00:00"),
    ]

    selected = scanner._select_scan_candidates(accounts, FakeSettings(max_sleep_per_scan=2), now)

    assert_equal([item[0]["id"] for item in selected], [1, 2, 11, 12], "per-platform max selection")


if __name__ == "__main__":
    tests = [
        test_evaluate_openai_chooses_later_reset_window_when_both_hit,
        test_evaluate_openai_ignores_expired_reset_window,
        test_evaluate_openai_accepts_iso_seconds_and_milliseconds_reset_times,
        test_evaluate_anthropic_multiplies_fraction_utilization_by_100,
        test_evaluate_anthropic_chooses_later_7d_reset_when_both_windows_hit,
        test_select_sleep_candidates_skips_accounts_with_existing_later_reset,
        test_select_sleep_candidates_allows_existing_earlier_reset_to_extend_sleep,
        test_select_scan_candidates_applies_max_sleep_per_scan_per_platform,
    ]
    for test in tests:
        try:
            test()
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            raise
        else:
            print(f"PASS {test.__name__}")
