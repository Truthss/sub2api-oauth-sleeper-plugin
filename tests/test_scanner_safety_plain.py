from datetime import datetime, timezone
from pathlib import Path
import sys
import types

scanner_path = Path(__file__).resolve().parents[1] / "app" / "scanner.py"
source = scanner_path.read_text(encoding="utf-8")
start = source.index("@dataclass")
end = source.index("async def scan_once")
logic = source[start:end]
module = types.ModuleType("scanner_logic_under_test")
sys.modules[module.__name__] = module
ns = module.__dict__
ns.update({"datetime": datetime, "timezone": timezone, "Any": object})
exec("from dataclasses import dataclass\n" + logic, ns)

select_sleep_candidates = ns["select_sleep_candidates"]


def account(account_id: int, percent: float) -> dict:
    return {
        "id": account_id,
        "name": f"acct-{account_id}",
        "platform": "openai",
        "rate_limit_reset_at": None,
        "extra": {
            "codex_7d_used_percent": percent,
            "codex_7d_reset_at": "2026-05-21T22:00:00+00:00",
        },
    }


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_respects_max_per_scan_without_min_remaining_floor() -> None:
    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    accounts = [account(1, 100), account(2, 99), account(3, 98), account(4, 10), account(5, 5)]
    selected = select_sleep_candidates(accounts, 90, now, "openai", 3)
    assert_equal([a["id"] for a, _ in selected], [1, 2, 3], "max per scan selection")
    assert_equal(selected[0][1].window_name, "7d", "decision window")


def test_zero_max_per_scan_disables_sleeping() -> None:
    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    selected = select_sleep_candidates([account(1, 100), account(2, 99), account(3, 10)], 90, now, "openai", 0)
    assert_equal(selected, [], "zero max per scan")


def test_orders_by_highest_utilization_first() -> None:
    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    accounts = [account(1, 91), account(2, 100), account(3, 95), account(4, 1), account(5, 1)]
    selected = select_sleep_candidates(accounts, 90, now, "openai", 2)
    assert_equal([a["id"] for a, _ in selected], [2, 3], "utilization ordering")


if __name__ == "__main__":
    tests = [
        test_respects_max_per_scan_without_min_remaining_floor,
        test_zero_max_per_scan_disables_sleeping,
        test_orders_by_highest_utilization_first,
    ]
    for test in tests:
        try:
            test()
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            raise
        else:
            print(f"PASS {test.__name__}")
