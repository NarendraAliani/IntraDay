# tests/conftest.py
#
# Checkpoint 17.2: project-wide test fixtures. First fixture here: cache
# isolation between tests.
#
# Root cause (Checkpoint 17.1 finding): `intraday.settings.testing`'s
# `CACHES["default"]` is Django's `LocMemCache`, which is a real
# in-process cache backend, not a per-test-isolated fake - the same
# backend instance is reused across every test in a pytest run (Django
# never tears it down between tests on its own). DRF's login-view
# throttle (`ScopedRateThrottle`, "login": "5/min", see settings/base.py)
# stores its per-IP request-count keys in exactly this cache. Once 5
# logins have occurred anywhere earlier in the same pytest process, every
# later test that logs in gets a real 429 - not because of anything that
# test does wrong, but because of state a completely unrelated, earlier
# test left behind.
#
# Fix: clear the cache before every test. This is test-isolation only -
# it does not touch, weaken, or bypass the throttle itself (still
# "5/min", still backed by the real cache backend the corresponding
# production/development environment uses - Redis there, LocMemCache
# here); it only ensures each test starts from the same clean state a
# fresh production request window would eventually reach on its own once
# the rate-limit window expired. `autouse=True` so no individual test
# file needs to remember to request it - matches this project's existing
# preference for tests that are correct by default rather than by
# convention (e.g. `requires_postgres`'s own collection-time skipif).
from __future__ import annotations

from collections.abc import Iterator

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache_between_tests() -> Iterator[None]:
    cache.clear()
    yield
    cache.clear()


# Checkpoint 64.18 §1: investigated the recurring
# `PytestWarning: Error when trying to teardown test databases: ...
# database "test_intraday" is being accessed by other users` seen at the
# end of every full-suite run. Root-caused as HARMLESS infrastructure
# noise, not a test-isolation bug:
#
#   - It always names the SAME single lingering session, regardless of
#     which tests ran or in what order - inconsistent with a specific
#     test leaking a connection (a real leak would vary with test
#     selection/order).
#   - It fires only ONCE, at the very end of the whole run, during
#     Django's own final `DROP DATABASE` - never during any individual
#     test's setup/teardown, and never causes a test failure.
#   - The ONE place in this suite with a genuine multi-connection risk
#     (`test_scanner_configuration_repository.py`'s `ThreadPoolExecutor`
#     concurrency test) already explicitly calls
#     `connections.close_all()` in a `finally` block - audited this
#     checkpoint, confirmed correct.
#   - The remaining session is this SAME pytest process's own long-lived
#     default Django DB connection (opened lazily the first time any
#     test touches the DB) - it is simply still open when pytest-django
#     asks a SEPARATE admin connection to `DROP DATABASE test_intraday`
#     at session end. Postgres correctly refuses to drop a database with
#     any other live session attached, including the test process's own.
#
# Safe fix: explicitly close every Django DB connection in THIS process
# before pytest-django's teardown runs, via `pytest_sessionfinish`
# (fires after all tests but before pytest-django's own database
# teardown, which is registered as an even later session-finish hook by
# `pytest-django`'s plugin registration order). This never touches any
# individual test's isolation or transaction behavior - only closes
# connections after every test has already finished.
def pytest_sessionfinish() -> None:
    try:
        from django.db import connections
    except Exception:  # pragma: no cover - Django not configured yet
        return
    connections.close_all()
