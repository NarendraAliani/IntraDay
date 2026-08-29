# File: tests/unit/research/test_checkpoint_65_12_provenance.py
#
# Checkpoint 65.12: targeted tests for the additive per-provider
# provenance mechanism (`domain.market_data.provenance`,
# `HistoricalBar.provenance`, migration 0036) and the two 65.01
# root-cause bugs it fixes:
#
#   1. `HistoricalDataPreparationService` used to write the same
#      provenance label regardless of which provider actually ran.
#   2. `SyntheticHistoricalBarProvider` gave no honest signal that its
#      output is synthetic, not genuine market data.
#
# Pure unit / targeted-DB tests, offline, no live Dhan connection, no
# strategy/Gainz/Market-Context/backtest-execution code touched.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.application.services.historical_data_coverage import (
    HistoricalDataCoverageService,
)
from intraday.application.services.historical_data_preparation import (
    HistoricalDataPreparationService,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.provenance import (
    PROVENANCE_CHOICES,
    PROVENANCE_REAL_DHAN,
    PROVENANCE_SYNTHETIC_TEST,
    PROVENANCE_UNKNOWN,
    is_research_eligible,
)
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.market_data_providers.synthetic_historical import (
    SyntheticHistoricalBarProvider,
)
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)
from intraday.infrastructure.persistence.models import HistoricalBar

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
START = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)
END = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)


class TestProvenanceVocabulary:
    def test_three_states_are_mutually_exclusive_and_exhaustive(self) -> None:
        assert PROVENANCE_CHOICES == (
            PROVENANCE_REAL_DHAN,
            PROVENANCE_SYNTHETIC_TEST,
            PROVENANCE_UNKNOWN,
        )
        assert len(set(PROVENANCE_CHOICES)) == 3

    def test_only_real_dhan_is_research_eligible(self) -> None:
        assert is_research_eligible(PROVENANCE_REAL_DHAN) is True
        assert is_research_eligible(PROVENANCE_SYNTHETIC_TEST) is False
        assert is_research_eligible(PROVENANCE_UNKNOWN) is False


class TestSyntheticProviderDeclaresItsOwnProvenance:
    def test_provider_declares_synthetic_test(self) -> None:
        provider = SyntheticHistoricalBarProvider()
        assert provider.provenance == PROVENANCE_SYNTHETIC_TEST


@pytest.mark.django_db
class TestPreparationServiceStampsPerProviderProvenance:
    """65.01 root-cause bug #1: the preparation service must stamp the
    provenance the PROVIDER declares, not a single hardcoded label."""

    def test_synthetic_provider_writes_synthetic_test_provenance(self) -> None:
        bar_repository = DjangoHistoricalBarRepository()
        service = HistoricalDataPreparationService(
            coverage=HistoricalDataCoverageService(repository=bar_repository),
            provider=SyntheticHistoricalBarProvider(),
            writer=bar_repository,
        )

        service.prepare(RELIANCE, Timeframe.FIVE_MINUTE, START, END)

        rows = HistoricalBar.objects.filter(instrument_id=str(RELIANCE))
        assert rows.exists()
        assert all(row.provenance == PROVENANCE_SYNTHETIC_TEST for row in rows)
        # And never silently upgraded to REAL_DHAN.
        assert not rows.filter(provenance=PROVENANCE_REAL_DHAN).exists()

    def test_provider_without_declared_provenance_defaults_to_unknown(self) -> None:
        class _UndeclaredProvider:
            def fetch(
                self, instrument_id: object, timeframe: object, start: datetime, end: datetime
            ) -> tuple[Bar, ...]:
                return (
                    Bar(
                        instrument_id=RELIANCE,
                        timeframe=Timeframe.FIVE_MINUTE,
                        timestamp=START,
                        open=Decimal("100"),
                        high=Decimal("101"),
                        low=Decimal("99"),
                        close=Decimal("100.5"),
                        volume=Decimal("1000"),
                    ),
                )

        bar_repository = DjangoHistoricalBarRepository()
        service = HistoricalDataPreparationService(
            coverage=HistoricalDataCoverageService(repository=bar_repository),
            provider=_UndeclaredProvider(),
            writer=bar_repository,
        )

        service.prepare(RELIANCE, Timeframe.FIVE_MINUTE, START, END)

        row = HistoricalBar.objects.get(instrument_id=str(RELIANCE))
        assert row.provenance == PROVENANCE_UNKNOWN


@pytest.mark.django_db
class TestMigration0036DidNotRelabelExistingRows:
    """The migration itself is exercised at `migrate` time (not here),
    but the model-level contract it establishes - default UNKNOWN,
    never auto-upgraded - is pinned as an executable fact."""

    def test_bulk_upsert_without_explicit_provenance_defaults_to_unknown(self) -> None:
        bar_repository = DjangoHistoricalBarRepository()
        bar = Bar(
            instrument_id=RELIANCE,
            timeframe=Timeframe.FIVE_MINUTE,
            timestamp=START,
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=Decimal("1000"),
        )

        bar_repository.bulk_upsert((bar,), source="API_FETCH")

        row = HistoricalBar.objects.get(instrument_id=str(RELIANCE))
        assert row.provenance == PROVENANCE_UNKNOWN
