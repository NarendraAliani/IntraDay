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


# Checkpoint 64.18 §1 investigated the recurring `PytestWarning: Error
# when trying to teardown test databases: ... database "test_intraday"
# is being accessed by other users`, root-caused it as a harmless
# lingering same-process connection (not a test-isolation leak - the
# one real multi-connection risk in this suite,
# `test_scanner_configuration_repository.py`'s `ThreadPoolExecutor`
# test, already calls `connections.close_all()` correctly), and
# attempted a fix via a `pytest_sessionfinish` hook. That fix did NOT
# work - the warning still appeared in every full-suite run after it
# was added.
#
# Checkpoint 64.19 §13 root-caused WHY: read pytest-django's own
# `fixtures.py` source directly (`django_db_setup`, session-scoped) -
# `teardown_databases()` (where this exact warning is raised, in
# pytest-django's own `except Exception` handler around it) runs
# inside that FIXTURE's finalizer (the code after its `yield`), not in
# any pytest hook. Session-scoped fixture finalizers run during
# pytest's internal session-teardown phase, which completes BEFORE
# `pytest_sessionfinish` hooks are called - so the previous hook closed
# connections strictly too late to matter, exactly as 64.18 already
# suspected but had not yet confirmed against the actual source.
#
# The correct fix, per pytest's own documented fixture-teardown
# ordering: a finalizer only runs before another fixture's finalizer if
# it belongs to a fixture that REQUESTED (depends on) that fixture -
# dependents tear down before their dependencies. This fixture
# explicitly depends on `django_db_setup` so pytest guarantees this
# fixture's own teardown (closing every connection) runs BEFORE
# `django_db_setup`'s teardown attempts `DROP DATABASE`. `autouse=True`
# so every test session picks it up without any test file needing to
# request it. This is the smallest safe fix: it changes no test's
# isolation or transaction behavior, and closing already-finished
# connections after the whole session's tests have run cannot affect
# any test result.
@pytest.fixture(scope="session", autouse=True)
def _close_db_connections_before_teardown(django_db_setup: None) -> Iterator[None]:  # noqa: ARG001
    yield
    from django.db import connections

    connections.close_all()


# Checkpoint 64.19 §13 RESULT: verified via a full-suite run AFTER
# adding the fixture above - the warning STILL appears, identically.
# This proves the revised hypothesis wrong too: the lingering session
# is NOT this pytest process's own default Django connection (that one
# is now provably closed, in the correct fixture-teardown order, before
# `DROP DATABASE` is attempted). The true remaining session is
# something else this investigation could not identify without direct
# `pg_stat_activity` access on the Postgres server (outside what this
# checkpoint's tooling can safely inspect) - candidates include a
# separate tool/IDE holding a connection to `test_intraday` (e.g. a
# database client left open), or a connection pool on this development
# machine that is not part of the pytest process at all.
#
# Per this checkpoint's own explicit instruction ("if it cannot be
# safely resolved without changing project test semantics, do not force
# the fix"): DEFERRED. It is safe to defer because, across every
# checkpoint this warning has been observed (64.16-64.19), it has never
# once caused a test failure, never affected test isolation, and never
# varied with which tests ran - it is cosmetic teardown noise from this
# development environment, not a product or test-suite defect.
