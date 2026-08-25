# File: src/intraday/domain/market_data/archive_retention.py
#
# Checkpoint 64.73 Phase 6: the EXPLICIT retention policy for the daily
# market-data archive.
#
# 64.72 correctly found that no retention policy existed anywhere. The
# response is deliberately NOT "add a cleanup job". Deleting observed
# market data is irreversible - the data cannot be re-observed, only
# (at best) re-fetched from a provider that may not offer the same
# granularity - so an automatic deleter introduced casually is a
# far worse defect than unbounded growth.
#
# So this module makes retention a first-class, auditable POLICY VALUE
# with a fail-safe default (`RETAIN_FOREVER`), and provides the pure
# `select_purgeable_trading_dates()` decision function - but NOTHING in
# this checkpoint deletes anything. There is no scheduled job, no
# management command that removes rows, and no caller of this function
# in production code. It exists so the policy is written down,
# testable, and reviewable BEFORE any deletion capability is built on
# top of it (Phase 6's "document it as a controlled future capability
# rather than pretending it exists").
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from intraday.domain.market_data.archive import ArchiveStatus


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """How long observed market data is kept.

    `raw_observation_retention_days=None` means RETAIN FOREVER, and is
    the default for both layers. A finite value is only ever meaningful
    once something is actually built to act on it."""

    raw_observation_retention_days: int | None = None
    aggregated_bar_retention_days: int | None = None
    require_complete_before_purge: bool = True
    """A day may never be purged unless its archive status is COMPLETE.
    Purging a PARTIAL day would destroy the only record that the day
    was incompletely observed - the archive would silently forget its
    own gap, which is precisely the dishonesty this checkpoint exists
    to remove."""
    require_reconciled_before_purge: bool = True
    """A day may never be purged before it has been independently
    reconciled. Since 64.73 performs no reconciliation at all, this
    flag alone makes the purge set EMPTY today - by design."""

    @property
    def deletes_anything(self) -> bool:
        return (
            self.raw_observation_retention_days is not None
            or self.aggregated_bar_retention_days is not None
        )


RETAIN_FOREVER = RetentionPolicy()
"""The ACTIVE policy for Checkpoint 64.73. Nothing is ever deleted."""


@dataclass(frozen=True, slots=True)
class RetentionCandidate:
    trading_date: date
    status: ArchiveStatus
    reconciled: bool


def select_purgeable_trading_dates(
    candidates: Iterable[RetentionCandidate],
    *,
    policy: RetentionPolicy,
    today: date,
    layer: str = "raw",
) -> tuple[date, ...]:
    """Which trading dates a purge WOULD be permitted to remove under
    `policy`. Pure and side-effect free - it returns dates, it does not
    delete rows, and no production code path calls it yet.

    Returns an empty tuple whenever the policy retains forever, so the
    default configuration is structurally incapable of selecting
    anything for deletion."""
    horizon_days = (
        policy.raw_observation_retention_days
        if layer == "raw"
        else policy.aggregated_bar_retention_days
    )
    if horizon_days is None:
        return ()
    cutoff = today - timedelta(days=horizon_days)
    selected = [
        candidate.trading_date
        for candidate in candidates
        if candidate.trading_date < cutoff
        and not (
            policy.require_complete_before_purge and candidate.status is not ArchiveStatus.COMPLETE
        )
        and not (policy.require_reconciled_before_purge and not candidate.reconciled)
    ]
    return tuple(sorted(selected))


__all__ = [
    "RETAIN_FOREVER",
    "RetentionCandidate",
    "RetentionPolicy",
    "select_purgeable_trading_dates",
]
