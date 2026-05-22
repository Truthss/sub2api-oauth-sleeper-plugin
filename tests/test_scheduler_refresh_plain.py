import os
import socket
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.scheduler_refresh import RefreshRequest, refresh_scheduler, refresh_scheduler_if_enabled


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_refresh_scheduler_passes_request_to_adapter() -> None:
    calls: list[tuple[int, str, tuple[str, ...]]] = []

    def fake_adapter(group_id: int, platform: str, modes: tuple[str, ...]) -> None:
        calls.append((group_id, platform, modes))

    ok = refresh_scheduler(RefreshRequest(group_id=7, platform="openai", modes=("single",)), fake_adapter)

    assert_equal(ok, True, "refresh result")
    assert_equal(calls, [(7, "openai", ("single",))], "adapter call")


def test_refresh_scheduler_downgrades_os_error() -> None:
    def failing_adapter(group_id: int, platform: str, modes: tuple[str, ...]) -> None:
        raise socket.gaierror(-5, "No address associated with hostname")

    ok = refresh_scheduler(RefreshRequest(group_id=2, platform="openai", modes=("single",)), failing_adapter)

    assert_equal(ok, False, "refresh failure is downgraded")


def test_refresh_scheduler_if_enabled_uses_env_defaults() -> None:
    original_env = os.environ.copy()
    calls: list[tuple[int, str, tuple[str, ...]]] = []

    def fake_adapter(group_id: int, platform: str, modes: tuple[str, ...]) -> None:
        calls.append((group_id, platform, modes))

    try:
        os.environ.clear()
        ok = refresh_scheduler_if_enabled(fake_adapter)
        assert_equal(ok, True, "default enabled result")
        assert_equal(calls, [(2, "openai", ("single",))], "default request")
    finally:
        os.environ.clear()
        os.environ.update(original_env)


def test_refresh_scheduler_if_enabled_respects_disabled_env() -> None:
    original_env = os.environ.copy()
    calls: list[tuple[int, str, tuple[str, ...]]] = []

    def fake_adapter(group_id: int, platform: str, modes: tuple[str, ...]) -> None:
        calls.append((group_id, platform, modes))

    try:
        os.environ["REFRESH_SUB2API_SCHEDULER"] = "false"
        ok = refresh_scheduler_if_enabled(fake_adapter)
        assert_equal(ok, False, "disabled result")
        assert_equal(calls, [], "disabled adapter call")
    finally:
        os.environ.clear()
        os.environ.update(original_env)


if __name__ == "__main__":
    tests = [
        test_refresh_scheduler_passes_request_to_adapter,
        test_refresh_scheduler_downgrades_os_error,
        test_refresh_scheduler_if_enabled_uses_env_defaults,
        test_refresh_scheduler_if_enabled_respects_disabled_env,
    ]
    for test in tests:
        try:
            test()
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            raise
        else:
            print(f"PASS {test.__name__}")
