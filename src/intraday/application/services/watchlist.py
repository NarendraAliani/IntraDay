# File: src/intraday/application/services/watchlist.py
#
# Checkpoint 27 Part 19: lightweight, research-only watchlist service.
# No order/quantity/side concept exists anywhere in this file.
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from intraday.application.repositories import WatchlistRepository
from intraday.application.services.errors import ResourceNotFoundError


@dataclass
class WatchlistService:
    repository: WatchlistRepository

    def save(self, name: str, owner: str, instrument_ids: list[str]) -> None:
        if not name.strip():
            raise ValueError("watchlist name must be non-empty")
        self.repository.save(name, owner, instrument_ids, created_at=_dt.datetime.now(tz=_dt.UTC))

    def get(self, name: str, owner: str) -> list[str]:
        instruments = self.repository.get(name, owner)
        if instruments is None:
            raise ResourceNotFoundError(f"no watchlist named {name!r} for {owner!r}")
        return instruments

    def list_for_owner(self, owner: str) -> tuple[str, ...]:
        return self.repository.list_for_owner(owner)

    def delete(self, name: str, owner: str) -> None:
        self.repository.delete(name, owner)
