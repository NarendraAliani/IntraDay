# File: src/intraday/infrastructure/system/process_liveness.py
#
# Checkpoint 67.12.2-S: the REAL, OS-facing half of PID-verified startup
# reconciliation. `worker_status_reconciliation.py` (application layer)
# takes a `probe_process` callable and does not know or care how it is
# implemented - fakes exercise the decision logic in tests, and THIS
# module is the real implementation wired in by the management commands.
#
# psutil is NOT a dependency of this project (confirmed: absent from
# both `pyproject.toml`'s direct dependencies and the active venv -
# `poetry.lock` mentions it only inside OTHER packages' own optional
# extras, e.g. mypy's `dmypy` extra, never as something this project's
# own code can import). Rather than adding a new dependency for one
# narrow need, this uses the Windows APIs that are actually available:
#
#   - liveness + start time: `ctypes` + `kernel32.OpenProcess`/
#     `GetProcessTimes` - the documented, race-free way to both ask "is
#     this PID alive" and get its creation time in one syscall, without
#     the process ever being visible long enough for os.kill(pid, 0)'s
#     POSIX-only "signal 0" trick (which Windows does not implement the
#     same way at all - CTRL_C_EVENT, not a liveness probe).
#   - command line: `Get-CimInstance Win32_Process` via a short-lived
#     PowerShell subprocess - the SAME mechanism the user's own manual
#     investigation used today, kept here as a best-effort SECOND
#     signal (start-time comparison from GetProcessTimes is the primary,
#     always-available disambiguator; a cmdline query that fails/times
#     out degrades to an empty string, never raises).
#
# Cross-platform note: this project's tests and production both run on
# Windows (see CLAUDE.md environment) - a POSIX fallback path is
# provided for completeness/portability but is NOT exercised by this
# checkpoint's own test suite (which runs on Windows).
from __future__ import annotations

import ctypes
import datetime as dt
import os
import subprocess
import sys
from dataclasses import dataclass

_WIN32_EPOCH_OFFSET_US = 11_644_473_600_000_000
"""Microseconds between the Windows FILETIME epoch (1601-01-01) and the
Unix epoch (1970-01-01) - the standard documented constant for this
conversion."""

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_CMDLINE_MAX_LEN = 500
"""Matches `WorkerRuntimeStatus.owner_cmdline_safe`'s own `max_length`."""


@dataclass(frozen=True, slots=True)
class ProcessSnapshot:
    """What this host can currently, honestly say about one live PID."""

    pid: int
    started_at: dt.datetime | None
    """The process's OS creation time (UTC, aware) - `None` only if the
    OS call itself failed for a genuinely alive process (never treated
    as "not alive")."""
    cmdline_safe: str
    """Best-effort, truncated, never a credential - empty string if the
    query failed or timed out."""


def current_process_identity() -> ProcessSnapshot:
    """The identity THIS process should stamp onto the
    `WorkerRuntimeStatus` row it is about to own - always has a real
    `pid` (from `os.getpid()`), best-effort for the rest."""
    pid = os.getpid()
    probed = probe_process(pid)
    if probed is not None:
        return probed
    return ProcessSnapshot(pid=pid, started_at=None, cmdline_safe="")


def probe_process(pid: int) -> ProcessSnapshot | None:
    """Returns a `ProcessSnapshot` if `pid` is genuinely alive on this
    host right now, `None` if it is not (exited, never existed, or
    access denied in a way that itself proves it is not OUR process).
    Never raises - a probe failure is reported as "not alive", the
    fail-safe direction for a reconciliation check whose job is to
    distrust an unverifiable claim."""
    if sys.platform != "win32":
        return _probe_process_posix(pid)
    return _probe_process_windows(pid)


def _probe_process_windows(pid: int) -> ProcessSnapshot | None:
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:

        class _FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

        creation, exit_t, kernel_t, user_t = (_FILETIME(), _FILETIME(), _FILETIME(), _FILETIME())
        ok = kernel32.GetProcessTimes(
            handle, ctypes.byref(creation), ctypes.byref(exit_t), ctypes.byref(kernel_t), ctypes.byref(user_t)
        )
        started_at = _filetime_to_datetime(creation) if ok else None
        return ProcessSnapshot(pid=pid, started_at=started_at, cmdline_safe=_query_cmdline_windows(pid))
    finally:
        kernel32.CloseHandle(handle)


def _filetime_to_datetime(ft: object) -> dt.datetime:
    high = getattr(ft, "dwHighDateTime")
    low = getattr(ft, "dwLowDateTime")
    total_us = ((high << 32) | low) // 10 - _WIN32_EPOCH_OFFSET_US
    return dt.datetime.fromtimestamp(total_us / 1_000_000, tz=dt.UTC)


def _query_cmdline_windows(pid: int) -> str:
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:  # noqa: BLE001 - best-effort only, never fatal to the probe
        return ""
    return (completed.stdout or "").strip()[:_CMDLINE_MAX_LEN]


def _probe_process_posix(pid: int) -> ProcessSnapshot | None:  # pragma: no cover - not this project's platform
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return ProcessSnapshot(pid=pid, started_at=None, cmdline_safe="")


__all__ = ["ProcessSnapshot", "current_process_identity", "probe_process"]
