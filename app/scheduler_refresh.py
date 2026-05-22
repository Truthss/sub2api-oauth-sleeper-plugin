from __future__ import annotations

import logging
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)
RefreshAdapter = Callable[[int, str, tuple[str, ...]], None]


@dataclass(frozen=True)
class RefreshRequest:
    group_id: int
    platform: str
    modes: tuple[str, ...]


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


def refresh_sub2api_scheduler(
    group_id: int = 2,
    platform: str = "openai",
    modes: tuple[str, ...] = ("single",),
) -> None:
    redis_host = os.getenv("SUB2API_REDIS_HOST", "redis")
    redis_port = _env_int("SUB2API_REDIS_PORT", 6379)

    def redis_command(*parts: str) -> str:
        payload = "*" + str(len(parts)) + "\r\n" + "".join(f"${len(p.encode())}\r\n{p}\r\n" for p in parts)
        with socket.create_connection((redis_host, redis_port), timeout=5) as sock:
            sock.sendall(payload.encode())
            sock.shutdown(socket.SHUT_WR)
            return sock.recv(1024 * 1024).decode(errors="replace")

    def parse_bulk(resp: str) -> str:
        if not resp.startswith("$"):
            return ""
        _, rest = resp.split("\r\n", 1)
        if rest.startswith("-1"):
            return ""
        return rest.split("\r\n", 1)[0]

    def parse_array(resp: str) -> list[str]:
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

    keys_to_delete: list[str] = []
    for mode in modes:
        active_key = f"sched:active:{group_id}:{platform}:{mode}"
        ver = parse_bulk(redis_command("GET", active_key))
        keys_to_delete.extend([
            active_key,
            f"sched:ready:{group_id}:{platform}:{mode}",
            f"sched:ver:{group_id}:{platform}:{mode}",
            f"sched:lock:{group_id}:{platform}:{mode}",
        ])
        if ver:
            keys_to_delete.append(f"sched:{group_id}:{platform}:{mode}:v{ver}")
    cursor = "0"
    pattern = f"sticky_session:{group_id}:{platform}:*"
    while True:
        resp = redis_command("SCAN", cursor, "MATCH", pattern, "COUNT", "100")
        arr = parse_array(resp)
        if not arr:
            break
        cursor = arr[0]
        keys_to_delete.extend(arr[1:])
        if cursor == "0":
            break
    if keys_to_delete:
        redis_command("DEL", *keys_to_delete)
