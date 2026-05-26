import os
import socket
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.scheduler_refresh import (
    RedisCommandPort,
    RefreshRequest,
    SchedulerRefreshPlan,
    build_scheduler_refresh_plan,
    refresh_scheduler,
    refresh_scheduler_if_enabled,
)


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


class FakeRedisPort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.values: dict[str, str] = {
            "sched:active:2:openai:single": "9",
        }
        self.scan_pages: list[tuple[str, list[str]]] = [
            ("0", ["sticky_session:2:openai:abc", "sticky_session:2:openai:def"]),
        ]

    def get(self, key: str) -> str:
        self.calls.append(("GET", key))
        return self.values.get(key, "")

    def scan(self, cursor: str, match: str, count: int) -> tuple[str, list[str]]:
        self.calls.append(("SCAN", cursor, "MATCH", match, "COUNT", str(count)))
        if not self.scan_pages:
            return "0", []
        return self.scan_pages.pop(0)

    def delete(self, keys: list[str]) -> None:
        self.calls.append(("DEL", *keys))


def test_build_scheduler_refresh_plan_includes_active_version_keys() -> None:
    port = FakeRedisPort()
    plan = build_scheduler_refresh_plan(
        RefreshRequest(group_id=2, platform="openai", modes=("single",)),
        port,
    )

    assert_equal(
        plan.keys_to_delete,
        [
            "sched:active:2:openai:single",
            "sched:ready:2:openai:single",
            "sched:ver:2:openai:single",
            "sched:lock:2:openai:single",
            "sched:2:openai:single:v9",
            "sticky_session:2:openai:abc",
            "sticky_session:2:openai:def",
        ],
        "refresh plan keys",
    )


def test_scheduler_refresh_plan_deletes_keys_through_port() -> None:
    port = FakeRedisPort()
    typed_port: RedisCommandPort = port
    plan = SchedulerRefreshPlan(keys_to_delete=["a", "b"])

    plan.apply(typed_port)

    assert_equal(port.calls, [("DEL", "a", "b")], "plan delete call")


if __name__ == "__main__":
    tests = [
        test_refresh_scheduler_passes_request_to_adapter,
        test_refresh_scheduler_downgrades_os_error,
        test_refresh_scheduler_if_enabled_uses_env_defaults,
        test_refresh_scheduler_if_enabled_respects_disabled_env,
        test_build_scheduler_refresh_plan_includes_active_version_keys,
        test_scheduler_refresh_plan_deletes_keys_through_port,
    ]
    for test in tests:
        try:
            test()
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            raise
        else:
            print(f"PASS {test.__name__}")
