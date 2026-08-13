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
