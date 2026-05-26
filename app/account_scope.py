from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AccountScanScope:
    include_openai: bool
    include_anthropic: bool

    @property
    def platforms(self) -> tuple[str, ...]:
        platforms: list[str] = []
        if self.include_openai:
            platforms.append("openai")
        if self.include_anthropic:
            platforms.append("anthropic")
        return tuple(platforms)

    @property
    def is_empty(self) -> bool:
        return not self.platforms


@dataclass(frozen=True)
class AccountScanBatch:
    scanned_count: int
    eligible_accounts: list[dict[str, Any]]

    @property
    def eligible_count(self) -> int:
        return len(self.eligible_accounts)


def account_scope_from_settings(settings: Any) -> AccountScanScope:
    return AccountScanScope(
        include_openai=bool(settings.include_openai),
        include_anthropic=bool(settings.include_anthropic),
    )


def filter_whitelisted_accounts(
    accounts: list[dict[str, Any]],
    whitelisted_ids: set[int],
) -> list[dict[str, Any]]:
    if not whitelisted_ids:
        return accounts
    return [account for account in accounts if int(account["id"]) not in whitelisted_ids]
