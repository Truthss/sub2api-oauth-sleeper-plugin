from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from . import repository as repo
from .account_scope import AccountScanBatch
from .schemas import SleeperEvent


class ScanStore(Protocol):
    async def get_settings(self) -> Any:
        ...

    async def list_scan_account_batch(self, settings: Any) -> AccountScanBatch:
        ...

    async def set_rate_limited(self, account_id: int, reset_at: datetime) -> bool:
        ...

    async def insert_event(self, event: SleeperEvent) -> SleeperEvent:
        ...

    async def finish_scan(self, scanned: int, triggered: int) -> None:
        ...

    async def rollback_sleeps(self, account_ids: list[int]) -> None:
        ...


@dataclass(frozen=True)
class RepositoryScanStore:
    rollback_sleeps_impl: Callable[[list[int]], Awaitable[None]]

    async def get_settings(self) -> Any:
        return await repo.get_settings()

    async def list_scan_account_batch(self, settings: Any) -> AccountScanBatch:
        return await repo.list_scan_account_batch(settings)

    async def set_rate_limited(self, account_id: int, reset_at: datetime) -> bool:
        return await repo.set_rate_limited(account_id, reset_at)

    async def insert_event(self, event: SleeperEvent) -> SleeperEvent:
        return await repo.insert_event(event)

    async def finish_scan(self, scanned: int, triggered: int) -> None:
        await repo.update_last_scan(scanned, triggered)

    async def rollback_sleeps(self, account_ids: list[int]) -> None:
        await self.rollback_sleeps_impl(account_ids)
