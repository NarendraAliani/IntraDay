# tests/unit/infrastructure/persistence/test_checkpoint_64_92_archive_observability_and_lineage.py
#
# Checkpoint 64.92: real-database coverage for the two offline software
# gaps 64.91 identified.
#
#   PART A (observability): a cell with GENUINE persisted
#   `dhan_websocket`-sourced quotes and `dhan`-labelled bars (exactly
#   64.91's real shape - the live worker's WebSocket quotes carry the
#   finer `DHAN_WEBSOCKET_SOURCE` label while `BarAggregationService`
#   always stamps bars with the coarser `DHAN_DATA_SOURCE` label) must
#   populate `first_observation_at`/`last_observation_at`/
#   `quote_observation_count` from that genuine evidence, not leave them
#   NULL/0.
#
#   PART B (lineage): `MarketDataArchiveDay.session_purpose` is additive,
#   defaults UNKNOWN for a row nobody re-refreshes, and a `refresh_*`
#   call - today's only writer, always a genuine live path - stamps
#   LIVE, never REPLAY, and never touches an unrelated cell's purpose.
#
# No provider connection, no strategy, no order path is exercised here.
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.market_data_archive import MarketDataArchiveService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import AggregatedBar, BarStatus
from intraday.domain.market_data.archive import ArchiveStatus, SessionPurpose
from intraday.domain.market_data.contracts import Quote
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.market_data_providers.dhan.packet_to_quote import (
    DHAN_WEBSOCKET_SOURCE,
)
from intraday.infrastructure.persistence.live_market_data_repositories import (
    DjangoAggregatedBarRepository,
    DjangoLiveQuoteRepository,
)
from intraday.infrastructure.persistence.market_data_archive_repository import (
    DjangoMarketDataArchiveRepository,
)
from intraday.infrastructure.persistence.models import MarketDataArchiveDay
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TRADING_DAY = date(2026, 8, 25)
AFTER_CLOSE = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)  # 17:30 IST
Q1 = datetime(2026, 8, 25, 5, 0, tzinfo=UTC)
Q2 = datetime(2026, 8, 25, 5, 5, tzinfo=UTC)


def _websocket_quote(timestamp: datetime, price: str = "100.00") -> Quote:
    """A quote shaped exactly like the live Dhan WebSocket path
    persists it - `source=DHAN_WEBSOCKET_SOURCE`, never `"dhan"`."""
    return Quote(
        instrument_id=RELIANCE,
        last_price=Decimal(price),
        timestamp=timestamp,
        source=DHAN_WEBSOCKET_SOURCE,
        cumulative_volume=Decimal("1000"),
    )


def _dhan_bar(interval_start: datetime) -> AggregatedBar:
    """A bar shaped exactly like `BarAggregationService` persists it -
    `data_source="dhan"`, the coarse label, regardless of the finer
    `dhan_websocket` label on the quotes it was built from."""
    return AggregatedBar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.ONE_MINUTE,
        interval_start=interval_start,
        interval_end=interval_start + timedelta(minutes=1),
        open=Decimal("100.00"),
        high=Decimal("101.00"),
        low=Decimal("99.00"),
        close=Decimal("100.50"),
        status=BarStatus.CLOSED,
        observation_count=2,
        data_source="dhan",
    )


@requires_postgres
@pytest.mark.django_db
def test_a_genuine_websocket_quotes_populate_first_observation_at() -> None:
    DjangoLiveQuoteRepository().save_all(
        (_websocket_quote(Q1), _websocket_quote(Q2)), fetched_at=AFTER_CLOSE
    )
    DjangoAggregatedBarRepository().save_all((_dhan_bar(Q1),))

    service = MarketDataArchiveService(DjangoMarketDataArchiveRepository())
    assessments = service.refresh_trading_date(trading_date=TRADING_DAY, as_of=AFTER_CLOSE)

    cell = next(a for a in assessments if a.data_source == "dhan")
    assert cell.first_observation_at == Q1


@requires_postgres
@pytest.mark.django_db
def test_b_genuine_websocket_quotes_populate_last_observation_at() -> None:
    DjangoLiveQuoteRepository().save_all(
        (_websocket_quote(Q1), _websocket_quote(Q2)), fetched_at=AFTER_CLOSE
    )
    DjangoAggregatedBarRepository().save_all((_dhan_bar(Q1),))

    service = MarketDataArchiveService(DjangoMarketDataArchiveRepository())
    assessments = service.refresh_trading_date(trading_date=TRADING_DAY, as_of=AFTER_CLOSE)

    cell = next(a for a in assessments if a.data_source == "dhan")
    assert cell.last_observation_at == Q2


@requires_postgres
@pytest.mark.django_db
def test_c_quote_count_matches_canonical_live_quote_observation_source() -> None:
    DjangoLiveQuoteRepository().save_all(
        (_websocket_quote(Q1), _websocket_quote(Q2)), fetched_at=AFTER_CLOSE
    )
    DjangoAggregatedBarRepository().save_all((_dhan_bar(Q1),))

    service = MarketDataArchiveService(DjangoMarketDataArchiveRepository())
    assessments = service.refresh_trading_date(trading_date=TRADING_DAY, as_of=AFTER_CLOSE)

    cell = next(a for a in assessments if a.data_source == "dhan")
    assert cell.quote_observation_count == 2


@requires_postgres
@pytest.mark.django_db
def test_d_cell_with_no_matching_provider_family_stays_unknown() -> None:
    """A bar cell whose provider family genuinely has no quote evidence
    (an unrelated source, not a `dhan*` variant) must stay NULL/0 -
    never fabricated from an unrelated group."""
    DjangoLiveQuoteRepository().save_all(
        (Quote(instrument_id=RELIANCE, last_price=Decimal("1"), timestamp=Q1, source="other_vendor"),),
        fetched_at=AFTER_CLOSE,
    )
    DjangoAggregatedBarRepository().save_all((_dhan_bar(Q1),))

    service = MarketDataArchiveService(DjangoMarketDataArchiveRepository())
    assessments = service.refresh_trading_date(trading_date=TRADING_DAY, as_of=AFTER_CLOSE)

    cell = next(a for a in assessments if a.data_source == "dhan")
    assert cell.quote_observation_count == 0
    assert cell.first_observation_at is None
    assert cell.last_observation_at is None


@requires_postgres
@pytest.mark.django_db
def test_e_repeated_refresh_is_idempotent() -> None:
    DjangoLiveQuoteRepository().save_all(
        (_websocket_quote(Q1), _websocket_quote(Q2)), fetched_at=AFTER_CLOSE
    )
    DjangoAggregatedBarRepository().save_all((_dhan_bar(Q1),))

    service = MarketDataArchiveService(DjangoMarketDataArchiveRepository())
    first = service.refresh_trading_date(trading_date=TRADING_DAY, as_of=AFTER_CLOSE)
    second = service.refresh_trading_date(trading_date=TRADING_DAY, as_of=AFTER_CLOSE)

    assert MarketDataArchiveDay.objects.count() == 1
    assert first[0].quote_observation_count == second[0].quote_observation_count
    assert first[0].first_observation_at == second[0].first_observation_at
    assert first[0].status == second[0].status


@requires_postgres
@pytest.mark.django_db
def test_f_refresh_stamps_live_session_purpose() -> None:
    DjangoLiveQuoteRepository().save_all((_websocket_quote(Q1),), fetched_at=AFTER_CLOSE)
    DjangoAggregatedBarRepository().save_all((_dhan_bar(Q1),))

    service = MarketDataArchiveService(DjangoMarketDataArchiveRepository())
    assessments = service.refresh_trading_date(trading_date=TRADING_DAY, as_of=AFTER_CLOSE)

    assert assessments[0].session_purpose == SessionPurpose.LIVE
    row = MarketDataArchiveDay.objects.get()
    assert row.session_purpose == "LIVE"


@requires_postgres
@pytest.mark.django_db
def test_g_replay_purpose_is_preserved_when_explicitly_computed() -> None:
    """No writer stamps REPLAY today, but the persistence path must
    faithfully round-trip it when a future caller does."""
    from intraday.domain.market_data.archive import (
        TradingSessionIdentity,
        assess_archive_day,
    )
    from intraday.domain.session.calendar import build_session_for

    identity = TradingSessionIdentity(exchange=Exchange.NSE, trading_date=TRADING_DAY)
    session = build_session_for(TRADING_DAY, AFTER_CLOSE)
    assessment = assess_archive_day(
        identity=identity,
        instrument_symbol="RELIANCE",
        timeframe=Timeframe.ONE_MINUTE,
        data_source="replay_fixture",
        session=session,
        closed_bar_timestamps=(),
        forming_bar_count=0,
        quote_observation_count=5,
        first_observation_at=Q1,
        last_observation_at=Q2,
        as_of=AFTER_CLOSE,
        session_purpose=SessionPurpose.REPLAY,
    )
    DjangoMarketDataArchiveRepository().save_assessment(assessment, computed_at=AFTER_CLOSE)

    row = MarketDataArchiveDay.objects.get()
    assert row.session_purpose == "REPLAY"


@requires_postgres
@pytest.mark.django_db
def test_h_pre_64_92_style_row_reads_back_with_unknown_purpose() -> None:
    """A row created the way every pre-64.92 code path did - without any
    knowledge of `session_purpose` - must still read back cleanly with
    the safe UNKNOWN default, never crash and never silently become
    LIVE or REPLAY."""
    MarketDataArchiveDay.objects.create(
        exchange="NSE",
        trading_date=TRADING_DAY,
        instrument_symbol="RELIANCE",
        timeframe="1m",
        data_source="dhan",
    )
    row = MarketDataArchiveDay.objects.get()
    assert row.session_purpose == "UNKNOWN"

    record = DjangoMarketDataArchiveRepository().list_archive_days(
        trading_date=TRADING_DAY, exchange=Exchange.NSE
    )[0]
    assert record.session_purpose == SessionPurpose.UNKNOWN
    assert record.status == ArchiveStatus.NOT_OBSERVED


@requires_postgres
@pytest.mark.django_db
def test_i_live_and_replay_cells_do_not_merge_across_data_source() -> None:
    """A LIVE `dhan` cell and a hypothetical REPLAY cell for the SAME
    (date, symbol, timeframe) but a DIFFERENT `data_source` stay two
    distinct rows - the natural key already prevents a silent merge,
    and each keeps its own `session_purpose`."""
    DjangoLiveQuoteRepository().save_all((_websocket_quote(Q1),), fetched_at=AFTER_CLOSE)
    DjangoAggregatedBarRepository().save_all((_dhan_bar(Q1),))
    MarketDataArchiveService(DjangoMarketDataArchiveRepository()).refresh_trading_date(
        trading_date=TRADING_DAY, as_of=AFTER_CLOSE
    )

    from intraday.domain.market_data.archive import (
        TradingSessionIdentity,
        assess_archive_day,
    )
    from intraday.domain.session.calendar import build_session_for

    identity = TradingSessionIdentity(exchange=Exchange.NSE, trading_date=TRADING_DAY)
    session = build_session_for(TRADING_DAY, AFTER_CLOSE)
    replay_assessment = assess_archive_day(
        identity=identity,
        instrument_symbol="RELIANCE",
        timeframe=Timeframe.ONE_MINUTE,
        data_source="replay_fixture",
        session=session,
        closed_bar_timestamps=(),
        forming_bar_count=0,
        quote_observation_count=1,
        first_observation_at=Q1,
        last_observation_at=Q1,
        as_of=AFTER_CLOSE,
        session_purpose=SessionPurpose.REPLAY,
    )
    DjangoMarketDataArchiveRepository().save_assessment(replay_assessment, computed_at=AFTER_CLOSE)

    rows = {
        row.data_source: row.session_purpose
        for row in MarketDataArchiveDay.objects.filter(
            trading_date=TRADING_DAY, instrument_symbol="RELIANCE"
        )
    }
    assert rows == {"dhan": "LIVE", "replay_fixture": "REPLAY"}
