# File: .../management/commands/supervise_market_data_worker.py
#
# Checkpoint 67.12.2-H, Part 3: the bounded auto-restart supervisor.
# Today (67.12.2-E) recovering from two live crashes was ~2 people-hours
# of manual log archaeology plus an ad hoc orchestrator shell script that
# could sleep-until-a-fixed-time but could NOT detect a crash on its own.
# This command replaces that with a real, tested, single-log-file entry
# point.
#
# This is a thin CLI wrapper around
# `application.services.market_data_worker_supervisor.supervise_market_data_worker`
# - it wires REAL side effects (spawn `run_market_data_worker` as a real
# child process, poll the real `WorkerRuntimeStatus` row, use the EXISTING
# stop-request + `market_data_archive --refresh` mechanism, Checkpoint
# 64.73/67.12.2-C/E - never a new one) around that pure, independently
# testable core loop. It builds NO generic process-supervision framework
# beyond what this one command needs, and it never touches
# `ScannerConfiguration` - the spawned `run_market_data_worker` process
# reads that exactly as it always has.
from __future__ import annotations

import asyncio
import datetime as dt
import getpass
import sys

from django.core.management.base import BaseCommand, CommandParser

from intraday.application.services.market_data_archive import MarketDataArchiveService
from intraday.application.services.market_data_worker_supervisor import (
    SupervisorResult,
    supervise_market_data_worker,
)
from intraday.domain.market_data.archive import trading_date_for
from intraday.infrastructure.persistence.market_data_archive_repository import (
    DjangoMarketDataArchiveRepository,
)
from intraday.infrastructure.persistence.worker_runtime_status_repository import (
    DjangoWorkerRuntimeStatusRepository,
)


class Command(BaseCommand):
    help = (
        "Watch WorkerRuntimeStatus for --provider and restart "
        "`run_market_data_worker` (bounded by --max-restarts) whenever it "
        "observes the worker's genuinely-terminal FAILED state (Checkpoint "
        "67.12.2-H Part 1's stale-status fix). Stops cleanly at --session-end "
        "using the existing process-independent stop-request + archive-refresh "
        "mechanism. Never spawns a --provider other than the one given; never "
        "touches ScannerConfiguration itself."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--provider", default="dhan")
        parser.add_argument(
            "--max-restarts",
            type=int,
            required=True,
            help="Hard bound on the whole run's restart count - exhausting it "
            "stops the supervisor PERMANENTLY (never crash-loops indefinitely "
            "against a genuinely broken network or an expired credential).",
        )
        parser.add_argument(
            "--cooldown-seconds",
            type=float,
            required=True,
            help="Seconds to wait after a detected crash before restarting.",
        )
        parser.add_argument(
            "--session-end",
            required=True,
            help="ISO 8601 timestamp (e.g. 2026-09-03T15:30:00+05:30) - the "
            "supervisor requests a clean stop and exits at this instant, "
            "regardless of restart budget remaining.",
        )
        parser.add_argument(
            "--poll-interval-seconds",
            type=float,
            default=7.0,
            help="How often to check WorkerRuntimeStatus (default: %(default)s "
            "- a sensible 5-10s poll, never a tight loop).",
        )
        parser.add_argument(
            "--mode",
            choices=["observe-only", "paper"],
            default="observe-only",
            help="Forwarded verbatim to every spawned run_market_data_worker "
            "invocation.",
        )

    def handle(self, *args: object, **options: object) -> None:
        provider = str(options["provider"])
        max_restarts = int(str(options["max_restarts"]))
        cooldown_seconds = float(str(options["cooldown_seconds"]))
        poll_interval_seconds = float(str(options["poll_interval_seconds"]))
        mode = str(options["mode"])
        session_end = dt.datetime.fromisoformat(str(options["session_end"]))
        if session_end.tzinfo is None:
            raise SystemExit("--session-end must be timezone-aware (e.g. include +05:30 or Z).")

        status_repository = DjangoWorkerRuntimeStatusRepository()
        archive_service = MarketDataArchiveService(DjangoMarketDataArchiveRepository())

        child_process: asyncio.subprocess.Process | None = None

        async def start_worker() -> None:
            nonlocal child_process
            child_process = await asyncio.create_subprocess_exec(
                sys.executable,
                "manage.py",
                "run_market_data_worker",
                "--provider",
                provider,
                "--mode",
                mode,
            )
            self.stdout.write(
                self.style.WARNING(f"  spawned run_market_data_worker pid={child_process.pid}")
            )

        async def is_worker_alive() -> bool:
            return child_process is not None and child_process.returncode is None

        async def request_session_end_stop() -> None:
            try:
                requested_by = getpass.getuser()
            except Exception:  # pragma: no cover - environment-dependent
                requested_by = "supervise_market_data_worker"
            status_repository.request_stop(
                provider,
                requested_at=dt.datetime.now(tz=dt.UTC),
                requested_by=requested_by,
                reason_safe="session_end_reached",
            )

        async def wait_for_worker_exit() -> None:
            if child_process is not None:
                await child_process.wait()

        async def refresh_archive() -> None:
            now = dt.datetime.now(tz=dt.UTC)
            await asyncio.to_thread(
                archive_service.refresh_trading_date,
                trading_date=trading_date_for(now),
                as_of=now,
            )

        result = asyncio.run(
            supervise_market_data_worker(
                provider=provider,
                max_restarts=max_restarts,
                cooldown_seconds=cooldown_seconds,
                session_end=session_end,
                poll_interval_seconds=poll_interval_seconds,
                status_repository=status_repository,
                start_worker=start_worker,
                is_worker_alive=is_worker_alive,
                request_session_end_stop=request_session_end_stop,
                wait_for_worker_exit=wait_for_worker_exit,
                refresh_archive=refresh_archive,
                sleep=asyncio.sleep,
                now=lambda: dt.datetime.now(tz=dt.UTC),
            )
        )
        self._report(result)

    def _report(self, result: SupervisorResult) -> None:
        for entry in result.log:
            self.stdout.write(f"  [{entry.at.isoformat()}] {entry.event}: {entry.detail}")
        if result.stopped_cleanly:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Supervisor finished: stopped_cleanly=True restarts_used={result.restarts_used} "
                    f"final_worker_state={result.final_worker_state}"
                )
            )
        elif result.max_restarts_exhausted:
            self.stdout.write(
                self.style.ERROR(
                    f"Supervisor finished: max_restarts_exhausted=True "
                    f"restarts_used={result.restarts_used} "
                    f"final_worker_state={result.final_worker_state} - stopping permanently, "
                    "no further restart attempted. A human must investigate."
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(
                    f"Supervisor finished: stopped permanently, restarts_used={result.restarts_used} "
                    f"final_worker_state={result.final_worker_state} - see log above for reason."
                )
            )
