# File: tests/unit/research/test_checkpoint_64_75_observation_provenance.py
#
# Checkpoint 64.75: proof tests for RAW-OBSERVATION PROVENANCE - the one
# gap 64.75's market-data-collection audit found worth implementing.
#
# The gap: `Quote.source` already existed on the domain contract and was
# already stamped by the live Dhan path, but `LiveQuoteObservation` had
# no column for it. Provenance was DROPPED on write and reconstructed as
# `""` on read, so a replayed observation could not answer "where did
# this come from?" - while the aggregated and archive layers both could.
# Worse, `MarketDataArchiveDay`'s cell identity INCLUDES `data_source`,
# so a symbol-day observed by two sources attributed one undifferentiated
# quote count to both of its cells.
#
# DETERMINISTIC and OFFLINE: no socket, no Dhan, no live session. The
# ORM-level tests use synthetic quotes; the attribution tests use a fake
# repository, never a real database connection.
from __future__ import annotations

import datetime as dt
from datetime import date
from decimal import Decimal

import pytest

from intraday.application.repositories.market_data_archive import (
    BarCell,
    QuoteObservationSummary,
)
from intraday.application.services.market_data_archive import _summary_for_cell
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Quote
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe

TRADING_DAY = date(2026, 8, 25)
# 09:20 IST on that day - inside the session, and (crucially) a UTC
# instant whose naive `.date()` is the SAME day, so these tests isolate
# provenance rather than re-testing 64.73's trading-date rule.
OBSERVED_AT = dt.datetime(2026, 8, 25, 3, 50, tzinfo=dt.UTC)

DHAN = "dhan_websocket"


def _quote(*, symbol: str = "RELIANCE", source: str = DHAN) -> Quote:
    return Quote(
        instrument_id=make_instrument_id(Exchange.NSE, symbol),
        timestamp=OBSERVED_AT,
        last_price=Decimal("1234.5000"),
        source=source,
    )


def _cell(*, symbol: str = "RELIANCE", data_source: str = DHAN) -> BarCell:
    return BarCell(
        instrument_symbol=symbol,
        timeframe=Timeframe.ONE_MINUTE,
        data_source=data_source,
        closed_bar_close_timestamps=(),
        forming_bar_count=0,
    )


def _summary(
    *, symbol: str = "RELIANCE", data_source: str = DHAN, count: int = 1
) -> QuoteObservationSummary:
    return QuoteObservationSummary(
        instrument_symbol=symbol,
        observation_count=count,
        first_observation_at=OBSERVED_AT,
        last_observation_at=OBSERVED_AT,
        data_source=data_source,
    )


class TestProvenanceRoundTripsThroughPersistence:
    """raw observation -> normalization -> persistence -> replay."""

    @pytest.mark.django_db
    def test_quote_source_is_persisted_and_replayed_verbatim(self) -> None:
        from intraday.infrastructure.persistence.live_market_data_repositories import (
            DjangoLiveQuoteRepository,
        )

        repository = DjangoLiveQuoteRepository()
        repository.save_all((_quote(),), fetched_at=OBSERVED_AT)

        replayed = repository.get_observations(since=OBSERVED_AT)

        assert len(replayed) == 1
        # Before 64.75 this was `""` - provenance silently lost.
        assert replayed[0].source == DHAN

    @pytest.mark.django_db
    def test_persisted_row_carries_both_provenance_and_trading_date(self) -> None:
        """Provenance is stamped at the SAME single write boundary as
        64.73's `trading_date`, not by a second write path."""
        from intraday.infrastructure.persistence.live_market_data_repositories import (
            DjangoLiveQuoteRepository,
        )
        from intraday.infrastructure.persistence.models import LiveQuoteObservation

        DjangoLiveQuoteRepository().save_all((_quote(),), fetched_at=OBSERVED_AT)

        row = LiveQuoteObservation.objects.get()
        assert row.data_source == DHAN
        assert row.trading_date == TRADING_DAY

    @pytest.mark.django_db
    def test_sourceless_quote_stays_blank_and_is_never_given_a_provider(self) -> None:
        """`""` must mean "provenance not recorded" - never be quietly
        upgraded to a plausible-looking provider name."""
        from intraday.infrastructure.persistence.live_market_data_repositories import (
            DjangoLiveQuoteRepository,
        )
        from intraday.infrastructure.persistence.models import LiveQuoteObservation

        DjangoLiveQuoteRepository().save_all((_quote(source=""),), fetched_at=OBSERVED_AT)

        assert LiveQuoteObservation.objects.get().data_source == ""

    @pytest.mark.django_db
    def test_two_sources_for_one_symbol_are_summarised_separately(self) -> None:
        """The archive's evidence query must distinguish providers - this
        is the query whose symbol-only grouping caused double attribution."""
        from intraday.infrastructure.persistence.live_market_data_repositories import (
            DjangoLiveQuoteRepository,
        )
        from intraday.infrastructure.persistence.market_data_archive_repository import (
            DjangoMarketDataArchiveRepository,
        )

        DjangoLiveQuoteRepository().save_all(
            (_quote(), _quote(), _quote(source="dhan_rest")),
            fetched_at=OBSERVED_AT,
        )

        summaries = DjangoMarketDataArchiveRepository().quote_summaries_for_trading_date(
            exchange=Exchange.NSE, trading_date=TRADING_DAY
        )

        by_source = {s.data_source: s.observation_count for s in summaries}
        assert by_source == {DHAN: 2, "dhan_rest": 1}


class TestArchiveQuoteAttribution:
    """Which raw-observation group an archive cell is credited with."""

    def test_cell_is_credited_with_its_own_sources_observations(self) -> None:
        summaries = (_summary(count=7), _summary(data_source="dhan_rest", count=3))

        assert _summary_for_cell(summaries, _cell()).observation_count == 7
        assert _summary_for_cell(summaries, _cell(data_source="dhan_rest")).observation_count == 3

    def test_two_source_day_no_longer_double_counts(self) -> None:
        """The concrete pre-64.75 defect: both cells received 10."""
        summaries = (_summary(count=7), _summary(data_source="dhan_rest", count=3))

        credited = sum(
            _summary_for_cell(summaries, _cell(data_source=source)).observation_count
            for source in (DHAN, "dhan_rest")
        )
        assert credited == 10

    def test_legacy_unrecorded_provenance_is_still_attributed(self) -> None:
        """Every row persisted before migration 0029 carries `""`. A
        strict match alone would collapse the 64.62/64.70/64.72/64.74
        evidence days' quote counts to zero - a regression, not a fix."""
        summaries = (_summary(data_source="", count=4869),)

        assert _summary_for_cell(summaries, _cell()).observation_count == 4869

    def test_exact_match_wins_over_legacy_fallback(self) -> None:
        summaries = (_summary(data_source="", count=99), _summary(count=5))

        assert _summary_for_cell(summaries, _cell()).observation_count == 5

    def test_unobserved_symbol_has_no_summary(self) -> None:
        summaries = (_summary(symbol="TCS", count=5),)

        assert _summary_for_cell(summaries, _cell(symbol="RELIANCE")) is None


class TestOptionsInfrastructureIsHonestlyAbsent:
    """Checkpoint 64.75 Phase 3/4 finding, pinned as an executable fact
    rather than only a claim in a report: at 64.75 this project had NO
    stock options / OI / IV / Greeks data infrastructure. The test was
    written so that "when a future checkpoint DOES build them, it is
    forced to come here and update the recorded finding deliberately".

    CHECKPOINT 64.78 IS THAT CHECKPOINT, and this is that deliberate
    update. Two - and ONLY two - option observation models now exist:
    `OptionQuoteObservation` and `OpenInterestObservation`. IV, Greeks,
    option-chain snapshots and option bars remain explicitly DEFERRED
    and unbuilt, so the guard is narrowed rather than deleted: it still
    fails the moment any of those appears without a checkpoint coming
    here to say so."""

    def test_only_the_64_78_option_observation_models_exist(self) -> None:
        from django.apps import apps

        models = apps.get_app_config("persistence").get_models()
        model_names = {model.__name__.lower() for model in models}

        assert "optionquoteobservation" in model_names
        assert "openinterestobservation" in model_names
        assert not any(
            token in name
            for name in model_names
            for token in ("greek", "impliedvol", "optionchain", "optionbar")
        )
