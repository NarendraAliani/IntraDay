# File: src/intraday/infrastructure/market_data_providers/dhan/option_subscription.py
#
# Checkpoint 64.78, Phases 6-8: the smallest provider-layer capability
# that lets the EXISTING subscription machinery address the NSE_FNO
# segment, without touching the NSE_EQ path at all.
#
# WHAT WAS ACTUALLY MISSING. Almost nothing, and that is the point. The
# subscribe-message builder in `run_market_data_worker.py`
# (`_build_subscribe_messages()`, Checkpoint 64.4) already emits
# `{"ExchangeSegment": i.exchange_segment, "SecurityId": ...}` reading
# the segment PER INSTRUMENT off `DhanInstrument.exchange_segment`. It
# was never pinned to NSE_EQ; only the UNIVERSE feeding it was
# (`instruments.py::observation_universe()`, an equity symbol table
# whose dataclass merely DEFAULTS the segment to "NSE_EQ"). So the whole
# option-subscription capability is: produce the same `DhanInstrument`
# rows carrying `"NSE_FNO"`, from the 64.77 option instrument master.
#
# That is deliberately what this module does, and all it does. No
# parallel batching mechanism, no second transport, no new request-code
# vocabulary, and no change to the 100-instruments-per-message limit -
# reusing the proven path is the whole architectural point, and it means
# batching, chunk determinism and the documented limit are already
# correct for options by construction rather than by re-implementation.
from __future__ import annotations

from collections.abc import Iterable

from intraday.domain.instrument.options import OptionInstrumentRecord
from intraday.infrastructure.market_data_providers.dhan.instrument_master import NSE_FNO_SEGMENT
from intraday.infrastructure.market_data_providers.dhan.instruments import (
    NSE_EQ_SEGMENT,
    DhanInstrument,
)

__all__ = [
    "NSE_EQ_SEGMENT",
    "NSE_FNO_SEGMENT",
    "option_subscription_instruments",
]


def option_subscription_instruments(
    records: Iterable[OptionInstrumentRecord],
) -> tuple[DhanInstrument, ...]:
    """The active option subscription universe, as the SAME
    `DhanInstrument` rows the existing subscribe-message builder already
    consumes - so options and equities flow through one batching
    implementation, one transport, and one documented request code.

    INDEX OPTIONS ARE FILTERED HERE, unconditionally. This is a sweep
    over a possibly-mixed collection, which is the case 64.77 says to
    FILTER rather than raise on (`require_stock_option()` is for a
    specific named contract, not a sweep). It is also the last gate
    before bytes go on the wire: an OPTIDX contract that somehow reached
    this point still cannot become an active subscription, which is what
    makes "index options are not enabled" a structural property rather
    than a comment.

    `trading_symbol` is used as the `DhanInstrument.symbol` because that
    field is a human-facing label only - Dhan addresses instruments
    strictly by `(ExchangeSegment, SecurityId)`, both of which come
    straight from the verified instrument master. The canonical
    `OptionContract` identity is deliberately NOT squeezed into this
    string: identity resolution on the way back IN happens through
    `packet_to_option_observation.py`'s security_id index, never by
    parsing a symbol.

    Order is preserved exactly as given (the master service already
    returns a deterministic order), so repeated runs produce byte-
    identical batches - the property the batching tests rest on."""
    subscriptions: list[DhanInstrument] = []
    for record in records:
        if not record.contract.is_stock_option:
            continue
        identity = record.provider_identity
        subscriptions.append(
            DhanInstrument(
                symbol=identity.trading_symbol,
                security_id=identity.security_id,
                exchange_segment=identity.exchange_segment or NSE_FNO_SEGMENT,
            )
        )
    return tuple(subscriptions)
