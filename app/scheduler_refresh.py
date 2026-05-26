from __future__ import annotations

import logging
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)
RefreshAdapter = Callable[[int, str, tuple[str, ...]], None]


@dataclass(frozen=True)
class RefreshRequest:
    group_id: int
    platform: str
    modes: tuple[str, ...]


class RedisCommandPort(Protocol):
    def get(self, key: str) -> str:
        ...

    def scan(self, cursor: str, match: str, count: int) -> tuple[str, list[str]]:
        ...

    def delete(self, keys: list[str]) -> None:
        ...


@dataclass(frozen=True)
class SchedulerRefreshPlan:
    keys_to_delete: list[str]

    def apply(self, port: RedisCommandPort) -> None:
        if self.keys_to_delete:
            port.delete(self.keys_to_delete)


class SocketRedisPort:
    def __init__(self, host: str, port: int, timeout: int = 5) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def get(self, key: str) -> str:
        return _parse_bulk(self._command("GET", key))

    def scan(self, cursor: str, match: str, count: int) -> tuple[str, list[str]]:
        values = _parse_array(self._command("SCAN", cursor, "MATCH", match, "COUNT", str(count)))
        if not values:
            return "0", []
        return values[0], values[1:]

    def delete(self, keys: list[str]) -> None:
        self._command("DEL", *keys)

    def _command(self, *parts: str) -> str:
        payload = "*" + str(len(parts)) + "\r\n" + "".join(f"${len(p.encode())}\r\n{p}\r\n" for p in parts)
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.sendall(payload.encode())
            sock.shutdown(socket.SHUT_WR)
            return sock.recv(1024 * 1024).decode(errors="replace")


def _parse_bulk(resp: str) -> str:
    if not resp.startswith("$"):
        return ""
    _, rest = resp.split("\r\n", 1)
    if rest.startswith("-1"):
        return ""
    return rest.split("\r\n", 1)[0]


def _parse_array(resp: str) -> list[str]:
    if not resp.startswith("*"):
        return []
    lines = resp.split("\r\n")
    out: list[str] = []
    i = 1
    while i < len(lines):
        if lines[i].startswith("$") and i + 1 < len(lines):
            out.append(lines[i + 1])
            i += 2
        else:
            i += 1
    return out


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def current_refresh_request() -> RefreshRequest | None:
    if not _env_bool("REFRESH_SUB2API_SCHEDULER", True):
        return None
    return RefreshRequest(
        group_id=_env_int("SUB2API_OPENAI_GROUP_ID", 2),
        platform="openai",
        modes=("single",),
    )


def refresh_scheduler(request: RefreshRequest, adapter: RefreshAdapter) -> bool:
    try:
        adapter(request.group_id, request.platform, request.modes)
        return True
    except OSError as exc:
        logger.warning("failed to refresh Sub2API scheduler: %s", exc)
        return False


def refresh_scheduler_if_enabled(adapter: RefreshAdapter | None = None) -> bool:
    request = current_refresh_request()
    if request is None:
        return False
    return refresh_scheduler(request, adapter or refresh_sub2api_scheduler)


def build_scheduler_refresh_plan(request: RefreshRequest, port: RedisCommandPort) -> SchedulerRefreshPlan:
    keys_to_delete: list[str] = []
    for mode in request.modes:
        active_key = f"sched:active:{request.group_id}:{request.platform}:{mode}"
        version = port.get(active_key)
        keys_to_delete.extend([
            active_key,
            f"sched:ready:{request.group_id}:{request.platform}:{mode}",
            f"sched:ver:{request.group_id}:{request.platform}:{mode}",
            f"sched:lock:{request.group_id}:{request.platform}:{mode}",
        ])
        if version:
            keys_to_delete.append(f"sched:{request.group_id}:{request.platform}:{mode}:v{version}")

    cursor = "0"
    pattern = f"sticky_session:{request.group_id}:{request.platform}:*"
    while True:
        cursor, keys = port.scan(cursor, pattern, 100)
        keys_to_delete.extend(keys)
        if cursor == "0":
            break

    return SchedulerRefreshPlan(keys_to_delete=keys_to_delete)


def refresh_sub2api_scheduler(
    group_id: int = 2,
    platform: str = "openai",
    modes: tuple[str, ...] = ("single",),
) -> None:
    redis_host = os.getenv("SUB2API_REDIS_HOST", "redis")
    redis_port = _env_int("SUB2API_REDIS_PORT", 6379)
    request = RefreshRequest(group_id=group_id, platform=platform, modes=modes)
    port = SocketRedisPort(redis_host, redis_port)
    build_scheduler_refresh_plan(request, port).apply(port)
