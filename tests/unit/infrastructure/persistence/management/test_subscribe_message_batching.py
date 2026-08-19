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


def test_every_message_is_a_real_documented_request_code_15_subscribe() -> None:
    messages = _build_subscribe_messages(_instruments(150))
    for message in messages:
        body = json.loads(message)
        assert body["RequestCode"] == 15
        assert "InstrumentList" in body
