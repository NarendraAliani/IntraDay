# File: src/intraday/infrastructure/scheduling/distributed_lock.py
#
# Checkpoint 42 Part 10: concurrency/distributed-safety protection.
# Uses Django's own cache framework (`django.core.cache.cache`) rather
# than adding a new dependency - this project's `CACHES["default"]`
# backend is ALREADY Redis in production/development
# (`django.core.cache.backends.redis.RedisCache`, `settings/base.py`)
# and LocMemCache in testing, per the existing `REST_FRAMEWORK`
# throttle-cache precedent this module mirrors. `cache.add()` is an
# atomic set-if-not-exists at the backend level (both Redis's own
# `SET key value NX` and Django's LocMemCache implementation) - the
# same primitive a dedicated Redis lock library would use, without a
# new dependency for something the existing infrastructure already
# provides.
#
# Survives worker restart / Celery retry / Beat restart (Part 10's
# explicit requirement) because the lock lives in Redis, not in any
# worker process's memory - a crashed worker's lock still expires via
# `timeout_seconds`, never requiring a manual unlock.
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from django.core.cache import cache

_LOCK_KEY_PREFIX = "intraday:lock:"


class LockAlreadyHeldError(Exception):
    """Raised by `acquire()` when another process already holds the
    named lock - callers use this to detect and skip an overlapping
    execution rather than proceeding concurrently."""


@dataclass(frozen=True, slots=True)
class DistributedLock:
    """One named lock. `token` is a per-acquisition-attempt random
    value (not the lock's identity) - a future `release()` could check
    it to avoid releasing a lock this exact acquisition didn't hold
    (a well-known distributed-lock correctness concern), though this
    checkpoint's usage always releases via the `with acquire()` context
    manager in the same process/call stack that acquired it, so that
    extra check is not yet exercised."""

    name: str
    timeout_seconds: int = 90
    """Longer than the 60-second Beat cadence (Decision 181) so a lock
    from one tick cannot still be held (and therefore skip) the NEXT
    scheduled tick under normal conditions, but short enough that a
    genuinely crashed holder's lock expires well before an operator
    would need to intervene manually."""

    @property
    def _cache_key(self) -> str:
        return f"{_LOCK_KEY_PREFIX}{self.name}"

    def try_acquire(self) -> str | None:
        """Non-blocking - returns a token if the lock was acquired,
        `None` if another process already holds it. Never blocks/waits
        (Part 10's own "two ingestion ticks cannot process the same
        time window concurrently" is satisfied by the LATER tick simply
        skipping, never queueing behind the first)."""
        token = str(uuid.uuid4())
        acquired = cache.add(self._cache_key, token, timeout=self.timeout_seconds)
        return token if acquired else None

    def release(self, token: str) -> None:
        # Best-effort - if the lock already expired (the holder ran
        # longer than timeout_seconds), there is nothing to release;
        # never raise on a missing key.
        current = cache.get(self._cache_key)
        if current == token:
            cache.delete(self._cache_key)


@contextmanager
def acquire(name: str, *, timeout_seconds: int = 90) -> Iterator[bool]:
    """`with acquire("market-data-ingestion") as acquired: if not
    acquired: return` - the shape every caller in this checkpoint
    actually uses. Yields `True`/`False` rather than raising, since
    "another process is already running this" is an ORDINARY, expected
    outcome for a scheduled tick (not an exceptional one) -
    `LockAlreadyHeldError` remains available for a caller that
    genuinely wants raise-on-contention semantics instead."""
    lock = DistributedLock(name=name, timeout_seconds=timeout_seconds)
    token = lock.try_acquire()
    try:
        yield token is not None
    finally:
        if token is not None:
            lock.release(token)
