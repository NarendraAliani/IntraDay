#!/usr/bin/env python
"""Checkpoint 64.5 §18: the FIRST real, runnable benchmark harness for
the live scanner control plane. Deliberately scoped to what this
checkpoint could measure honestly without a live Dhan connection or a
full strategy/signal pipeline fixture:

    - subscription preparation (`_build_subscribe_messages` chunking)
    - scanner configuration apply latency (`DjangoScannerConfigurationRepository.save()`,
      a real Postgres round trip through `select_for_update()` + an
      `AuditLogEntry` write)

NOT measured here (disclosed, not fabricated - see taskReport.md
"Performance Harness"): bar processing latency, strategy evaluation
latency, and signal latency, which all require a running worker/strategy
pipeline fixture that does not exist as a benchmarkable unit yet. API
latency (HTTP round trip) is also not measured here - only the
repository-level DB latency it wraps.

Run with:  poetry run python scripts/dev/benchmark_scanner_control_plane.py
Requires a working Postgres connection (same settings the test suite
uses) - this hits a real database, not a mock.
"""

from __future__ import annotations

import os
import statistics
import time
import uuid

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "intraday.settings.development")

import django  # noqa: E402

django.setup()

from intraday.infrastructure.market_data_providers.dhan.instruments import (  # noqa: E402
    DhanInstrument,
)
from intraday.infrastructure.persistence.management.commands.run_market_data_worker import (  # noqa: E402
    _build_subscribe_messages,
)
from intraday.infrastructure.persistence.scanner_configuration_repository import (  # noqa: E402
    DjangoScannerConfigurationRepository,
)

INSTRUMENT_COUNTS = (10, 50, 100, 250, 500)
ITERATIONS = 50


def _percentiles(samples_ms: list[float]) -> dict[str, float]:
    ordered = sorted(samples_ms)
    n = len(ordered)

    def _pct(p: float) -> float:
        index = min(n - 1, int(round(p * (n - 1))))
        return ordered[index]

    return {
        "P50": _pct(0.50),
        "P95": _pct(0.95),
        "P99": _pct(0.99),
        "MAX": ordered[-1],
    }


def benchmark_subscription_preparation() -> None:
    print("\n=== Subscription Preparation (_build_subscribe_messages) ===")
    for count in INSTRUMENT_COUNTS:
        instruments = tuple(DhanInstrument(symbol=f"SYM{i}", security_id=i) for i in range(count))
        samples_ms: list[float] = []
        for _ in range(ITERATIONS):
            start = time.perf_counter()
            _build_subscribe_messages(instruments)
            samples_ms.append((time.perf_counter() - start) * 1000)
        stats = _percentiles(samples_ms)
        print(
            f"  n={count:>4}  P50={stats['P50']:.4f}ms  P95={stats['P95']:.4f}ms  "
            f"P99={stats['P99']:.4f}ms  MAX={stats['MAX']:.4f}ms"
        )


def benchmark_scanner_configuration_apply() -> None:
    print("\n=== Scanner Configuration Apply Latency (real Postgres, save()) ===")
    repository = DjangoScannerConfigurationRepository()
    samples_ms: list[float] = []
    for _i in range(ITERATIONS):
        start = time.perf_counter()
        repository.save(
            "dhan-benchmark",
            enabled=True,
            timeframe="5m",
            universe_mode="ALL_CONFIGURED",
            selected_instrument_ids=[],
            selected_watchlist_name="",
            selected_strategy_ids=["ema_crossover"],
            requested_by="benchmark",
            requested_by_user_id=1,
            request_id=str(uuid.uuid4()),
        )
        samples_ms.append((time.perf_counter() - start) * 1000)
    stats = _percentiles(samples_ms)
    print(
        f"  iterations={ITERATIONS}  P50={stats['P50']:.2f}ms  P95={stats['P95']:.2f}ms  "
        f"P99={stats['P99']:.2f}ms  MAX={stats['MAX']:.2f}ms  "
        f"mean={statistics.mean(samples_ms):.2f}ms"
    )
    print(
        "  NOTE: writes to provider='dhan-benchmark' (never 'dhan') so this never touches "
        "real scanner state. Not cleaned up automatically - safe to leave, or truncate manually."
    )


if __name__ == "__main__":
    benchmark_subscription_preparation()
    benchmark_scanner_configuration_apply()
    print(
        "\nNOT measured by this harness (requires a running worker/strategy pipeline fixture "
        "this checkpoint did not build - see taskReport.md 'Performance Harness'): bar "
        "processing latency, strategy evaluation latency, signal latency, HTTP API latency."
    )
