# tests/unit/domain/market_data/test_source_timestamp.py
#
# Checkpoint 67.1 Part 6 test 8: `SourceTimestampSemantics.UNKNOWN` must
# never be silently treated as OPEN (or CLOSE) by
# `canonicalize_close_timestamp` - a provider/endpoint whose convention
# has not been empirically established must fail loudly, not guess.
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from intraday.domain.market_data.source_timestamp import (
    SourceTimestampSemantics,
    UnknownSourceTimestampSemanticsError,
    canonicalize_close_timestamp,
)

_RAW = datetime(2024, 1, 1, 3, 45, tzinfo=UTC)
_FIVE_MINUTES = timedelta(minutes=5)


def test_open_semantics_shifts_forward_by_one_interval() -> None:
    assert canonicalize_close_timestamp(
        _RAW, SourceTimestampSemantics.OPEN, _FIVE_MINUTES
    ) == _RAW + _FIVE_MINUTES


def test_close_semantics_leaves_the_timestamp_unchanged() -> None:
    assert canonicalize_close_timestamp(
        _RAW, SourceTimestampSemantics.CLOSE, _FIVE_MINUTES
    ) == _RAW


def test_unknown_semantics_raises_rather_than_silently_assuming_open() -> None:
    """The one test case explicitly required by Checkpoint 67.1 Part 6
    #8: UNKNOWN must never be treated as OPEN (or as anything else) by
    default - it must raise."""
    with pytest.raises(UnknownSourceTimestampSemanticsError):
        canonicalize_close_timestamp(_RAW, SourceTimestampSemantics.UNKNOWN, _FIVE_MINUTES)
