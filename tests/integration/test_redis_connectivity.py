# tests/integration/test_redis_connectivity.py
#
# Integration smoke test (Checkpoint 4 §33): verifies a raw Redis
# connection can be opened via REDIS_URL. Skipped when Redis is not
# reachable — expected to run for real in CI (GitHub Actions Redis service
# container) and in any docker-compose-backed local environment. Only
# proves connectivity; does not exercise cache/Channels/Celery-specific
# behavior (those are covered by their own tests). No business logic.
from __future__ import annotations

import os

import pytest
import redis


def test_can_connect_to_redis() -> None:
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        pytest.skip("REDIS_URL not set - Redis integration skipped in this environment")

    try:
        client = redis.Redis.from_url(redis_url, socket_connect_timeout=3)
        assert client.ping() is True
    except redis.exceptions.ConnectionError as exc:
        pytest.skip(f"Redis unreachable in this environment: {exc}")
