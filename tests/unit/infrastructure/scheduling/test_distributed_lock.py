# tests/unit/infrastructure/scheduling/test_distributed_lock.py
#
# Checkpoint 42 Part 10: proves the distributed lock actually prevents
# overlapping acquisition and releases correctly - using Django's real
# cache framework (LocMemCache in this test environment), never a
# hand-rolled in-memory stand-in.
from __future__ import annotations

from django.core.cache import cache

from intraday.infrastructure.scheduling.distributed_lock import DistributedLock, acquire


def setup_function() -> None:
    cache.clear()


def test_first_acquisition_succeeds() -> None:
    lock = DistributedLock(name="test-lock")
    token = lock.try_acquire()
    assert token is not None


def test_second_concurrent_acquisition_fails_while_the_first_is_held() -> None:
    lock = DistributedLock(name="test-lock")
    first_token = lock.try_acquire()
    assert first_token is not None

    second_token = lock.try_acquire()
    assert second_token is None  # a second "worker" cannot also acquire it


def test_release_allows_a_subsequent_acquisition() -> None:
    lock = DistributedLock(name="test-lock")
    token = lock.try_acquire()
    assert token is not None
    lock.release(token)

    reacquired = lock.try_acquire()
    assert reacquired is not None


def test_release_with_the_wrong_token_does_not_release_someone_elses_lock() -> None:
    lock = DistributedLock(name="test-lock")
    real_token = lock.try_acquire()
    assert real_token is not None

    lock.release("not-the-real-token")

    # The real holder's lock must still be in place.
    still_locked = lock.try_acquire()
    assert still_locked is None


def test_acquire_context_manager_yields_true_when_available_and_releases_on_exit() -> None:
    with acquire("ctx-lock") as acquired:
        assert acquired is True
    # Released on exit - a second attempt now succeeds.
    with acquire("ctx-lock") as acquired_again:
        assert acquired_again is True


def test_acquire_context_manager_yields_false_when_already_held() -> None:
    with acquire("held-lock") as outer_acquired:
        assert outer_acquired is True
        with acquire("held-lock") as inner_acquired:
            assert inner_acquired is False


def test_different_lock_names_do_not_interfere() -> None:
    with acquire("lock-a") as a, acquire("lock-b") as b:
        assert a is True
        assert b is True
