# File: src/intraday/infrastructure/market_data_providers/replay/deterministic_bar_source.py
#
# Checkpoint 52: the ONE concrete implementation of
# `application.repositories.live_market_data.BarSource` this checkpoint
# provides. NOT a Dhan adapter - a deterministic, pre-seeded replay
# source, explicitly labelled as such everywhere it appears (module
# name, class name, docstrings, test names) so it can never be mistaken
# for live-market-data evidence. A real Dhan-tick-driven `BarSource`
# implementation remains a separate, undone, NAMED dependency (see
# `ACTIVE_PRODUCT_GAP_REGISTER.md`) - this module exists to prove the
# `BarSource` boundary is real and swappable, not to claim live
# capability it does not have.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe


@dataclass(frozen=True, slots=True)
class DeterministicReplayBarSource:
    """Wraps a fixed, pre-seeded sequence of `Bar`s per
    `(instrument_id, timeframe)` and reveals only the ones whose
    `timestamp <= as_of` on each call - simulating "bars arrive over
    time" without any real I/O, deterministically, for tests and for a
    scheduler that wants to call `run_active_loop_tick_from_source()`
    repeatedly exactly as it would against a real feed."""

    _bars_by_key: dict[tuple[InstrumentId, Timeframe], tuple[Bar, ...]] = field(
        default_factory=dict
    )

    @staticmethod
    def seeded(bars: tuple[Bar, ...]) -> DeterministicReplayBarSource:
        """Builds a source from a flat tuple of bars, grouping by each
        bar's own `(instrument_id, timeframe)` - the ordinary
        construction path (mirrors how test fixtures already build bar
        tuples throughout this project, e.g.
        `test_position_monitor_runtime.py::_uptrend_bars()`)."""
        grouped: dict[tuple[InstrumentId, Timeframe], list[Bar]] = {}
        for bar in bars:
            key = (bar.instrument_id, bar.timeframe)
            grouped.setdefault(key, []).append(bar)
        return DeterministicReplayBarSource(
            {key: tuple(sorted(value, key=lambda b: b.timestamp)) for key, value in grouped.items()}
        )

    def get_bars(
        self, *, instrument_id: InstrumentId, timeframe: Timeframe, as_of: datetime
    ) -> tuple[Bar, ...]:
        all_bars = self._bars_by_key.get((instrument_id, timeframe), ())
        return tuple(bar for bar in all_bars if bar.timestamp <= as_of)
