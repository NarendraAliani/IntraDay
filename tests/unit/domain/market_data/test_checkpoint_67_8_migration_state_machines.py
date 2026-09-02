# File: tests/unit/domain/market_data/test_checkpoint_67_8_migration_state_machines.py
#
# Checkpoint 67.8 Parts 7-8 — deterministic, exhaustive unit tests for
# the finalized run-level and unit-level migration state machines.
# Pure Python, no database.
from __future__ import annotations

import itertools

from intraday.domain.market_data.migration_state import (
    RUN_STATE_TRANSITIONS,
    UNIT_STATE_TRANSITIONS,
    MigrationRunState,
    MigrationUnitState,
    is_legal_run_transition,
    is_legal_unit_transition,
)

_EXPECTED_RUN_TRANSITIONS = {
    (MigrationRunState.PLANNED, MigrationRunState.RUNNING),
    (MigrationRunState.RUNNING, MigrationRunState.PARTIALLY_COMPLETED),
    (MigrationRunState.RUNNING, MigrationRunState.COMPLETED),
    (MigrationRunState.RUNNING, MigrationRunState.ABORTED),
    (MigrationRunState.PARTIALLY_COMPLETED, MigrationRunState.RUNNING),
    (MigrationRunState.PARTIALLY_COMPLETED, MigrationRunState.ABORTED),
    (MigrationRunState.PARTIALLY_COMPLETED, MigrationRunState.COMPLETED),
}


def test_run_state_transition_table_matches_directive_exactly() -> None:
    assert RUN_STATE_TRANSITIONS == _EXPECTED_RUN_TRANSITIONS


def test_no_run_state_self_loops() -> None:
    for state in MigrationRunState:
        assert not is_legal_run_transition(state, state)


def test_run_terminal_states_have_no_outgoing_transitions() -> None:
    for terminal in (MigrationRunState.COMPLETED, MigrationRunState.ABORTED):
        for target in MigrationRunState:
            assert not is_legal_run_transition(terminal, target)


def test_planned_is_the_only_run_entry_state() -> None:
    targets_of_incoming = {target for _, target in RUN_STATE_TRANSITIONS}
    assert MigrationRunState.PLANNED not in targets_of_incoming


def test_every_run_state_pair_is_classified_exhaustively() -> None:
    for current, target in itertools.product(MigrationRunState, MigrationRunState):
        expected = (current, target) in _EXPECTED_RUN_TRANSITIONS
        assert is_legal_run_transition(current, target) == expected


_EXPECTED_UNIT_TRANSITIONS = {
    (MigrationUnitState.PENDING, MigrationUnitState.REVALIDATING),
    (MigrationUnitState.REVALIDATING, MigrationUnitState.SAFE),
    (MigrationUnitState.REVALIDATING, MigrationUnitState.STOPPED_REVALIDATION_MISMATCH),
    (MigrationUnitState.REVALIDATING, MigrationUnitState.FAILED),
    (MigrationUnitState.SAFE, MigrationUnitState.MIGRATING),
    (MigrationUnitState.SAFE, MigrationUnitState.STOPPED_REVALIDATION_MISMATCH),
    (MigrationUnitState.MIGRATING, MigrationUnitState.COMMITTED),
    (MigrationUnitState.MIGRATING, MigrationUnitState.ROLLED_BACK),
    (MigrationUnitState.MIGRATING, MigrationUnitState.FAILED),
}


def test_unit_state_transition_table_matches_directive_exactly() -> None:
    assert UNIT_STATE_TRANSITIONS == _EXPECTED_UNIT_TRANSITIONS


def test_unit_terminal_states_have_no_outgoing_transitions() -> None:
    terminals = (
        MigrationUnitState.COMMITTED,
        MigrationUnitState.ROLLED_BACK,
        MigrationUnitState.STOPPED_REVALIDATION_MISMATCH,
        MigrationUnitState.FAILED,
    )
    for terminal in terminals:
        for target in MigrationUnitState:
            assert not is_legal_unit_transition(terminal, target)


def test_pending_is_the_only_unit_entry_state() -> None:
    targets_of_incoming = {target for _, target in UNIT_STATE_TRANSITIONS}
    assert MigrationUnitState.PENDING not in targets_of_incoming


def test_every_unit_state_pair_is_classified_exhaustively() -> None:
    for current, target in itertools.product(MigrationUnitState, MigrationUnitState):
        expected = (current, target) in _EXPECTED_UNIT_TRANSITIONS
        assert is_legal_unit_transition(current, target) == expected


def test_committed_and_rolled_back_are_mutually_exclusive_from_migrating() -> None:
    """A unit that reached MIGRATING can end in exactly one of
    COMMITTED/ROLLED_BACK/FAILED - never both, never neither, and never
    a state requiring MIGRATING to run twice (no MIGRATING ->
    MIGRATING self-loop)."""
    outgoing = {t for c, t in UNIT_STATE_TRANSITIONS if c is MigrationUnitState.MIGRATING}
    assert outgoing == {
        MigrationUnitState.COMMITTED,
        MigrationUnitState.ROLLED_BACK,
        MigrationUnitState.FAILED,
    }
