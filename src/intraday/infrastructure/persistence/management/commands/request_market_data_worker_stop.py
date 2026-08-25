# File: .../management/commands/request_market_data_worker_stop.py
#
# Checkpoint 64.73: the operator-facing half of the process-independent
# graceful-shutdown mechanism (see
# `application/services/worker_stop_request.py` for why OS signals were
# abandoned as the primary path after 64.72's three failed attempts).
#
# This command NEVER kills a process. It records a request; the running
# worker observes it and shuts itself down through its own orderly path
# (stop event -> provider disconnect -> aggregation drain -> persistence
# flush -> WorkerRuntimeStatus=STOPPED -> exit).
from __future__ import annotations

import datetime as dt
import getpass

from django.core.management.base import BaseCommand, CommandParser

from intraday.infrastructure.persistence.worker_runtime_status_repository import (
    DjangoWorkerRuntimeStatusRepository,
)


class Command(BaseCommand):
    help = "Request that a running market-data worker stop gracefully."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--provider", default="dhan")
        parser.add_argument(
            "--reason",
            default="operator_requested",
            help="Short, non-credential reason recorded alongside the request.",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Cancel a pending stop request instead of creating one.",
        )

    def handle(self, *args: object, **options: object) -> None:
        provider = str(options["provider"])
        repository = DjangoWorkerRuntimeStatusRepository()

        if bool(options.get("clear")):
            repository.clear_stop_request(provider)
            self.stdout.write(
                self.style.SUCCESS(f"cleared any pending stop request for provider={provider!r}")
            )
            return

        try:
            requested_by = getpass.getuser()
        except Exception:  # pragma: no cover - environment-dependent
            requested_by = "unknown"

        repository.request_stop(
            provider,
            requested_at=dt.datetime.now(tz=dt.UTC),
            requested_by=requested_by,
            reason_safe=str(options["reason"])[:255],
        )
        self.stdout.write(
            self.style.WARNING(
                f"stop requested for provider={provider!r}. The worker polls for this and "
                "will shut down gracefully; this command does not terminate any process."
            )
        )
