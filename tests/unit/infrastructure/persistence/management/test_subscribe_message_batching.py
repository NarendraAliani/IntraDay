# tests/unit/infrastructure/persistence/management/test_subscribe_message_batching.py
#
# Checkpoint 64.4: closes the "silently truncates to 100" gap named in
# Checkpoint 64.3's own report - proves a universe larger than Dhan's
# documented 100-instruments-per-message limit is split into multiple
# real subscribe messages, never truncated. Pure unit test - no
# network, no DB.
from __future__ import annotations

import json

from intraday.infrastructure.market_data_providers.dhan.instruments import DhanInstrument
from intraday.infrastructure.persistence.management.commands.run_market_data_worker import (
    SUBSCRIBE_REQUEST_CODE_QUOTE,
    SUBSCRIBE_REQUEST_CODE_TICKER,
    _build_subscribe_messages,
)


def _instruments(count: int) -> tuple[DhanInstrument, ...]:
    return tuple(DhanInstrument(symbol=f"SYM{i}", security_id=1000 + i) for i in range(count))


def test_a_universe_under_the_limit_is_one_message() -> None:
    messages = _build_subscribe_messages(_instruments(50))
    assert len(messages) == 1
    assert json.loads(messages[0])["InstrumentCount"] == 50


def test_a_universe_of_exactly_100_is_one_message() -> None:
    messages = _build_subscribe_messages(_instruments(100))
    assert len(messages) == 1
    assert json.loads(messages[0])["InstrumentCount"] == 100


def test_a_universe_of_287_is_split_into_100_100_87_never_truncated() -> None:
    messages = _build_subscribe_messages(_instruments(287))

    assert len(messages) == 3
    counts = [json.loads(m)["InstrumentCount"] for m in messages]
    assert counts == [100, 100, 87]
    # Nothing lost - every security_id appears in exactly one message.
    all_security_ids = {
        entry["SecurityId"]
        for message in messages
        for entry in json.loads(message)["InstrumentList"]
    }
    assert len(all_security_ids) == 287


def test_every_message_defaults_to_the_documented_quote_subscribe_request_code() -> None:
    """Checkpoint 64.71: the default changed from 15 to 17.

    Dhan's feed-request-code enum makes 15 mean "Subscribe - Ticker
    Packet", NOT a generic subscribe - which is exactly why Checkpoint
    64.70's live session received only Ticker packets and could never
    obtain real volume. 17 is "Subscribe - Quote Packet"."""
    messages = _build_subscribe_messages(_instruments(150))
    for message in messages:
        body = json.loads(message)
        assert body["RequestCode"] == SUBSCRIBE_REQUEST_CODE_QUOTE == 17
        assert "InstrumentList" in body


def test_ticker_mode_is_still_expressible_for_an_explicit_caller() -> None:
    """The Ticker code is not deleted, only stopped being the default -
    a live session that needed to fall back has a real, documented way
    to ask for it."""
    messages = _build_subscribe_messages(
        _instruments(10), request_code=SUBSCRIBE_REQUEST_CODE_TICKER
    )
    assert [json.loads(m)["RequestCode"] for m in messages] == [15]
