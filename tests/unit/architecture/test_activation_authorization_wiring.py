# tests/unit/architecture/test_activation_authorization_wiring.py
#
# Checkpoint 13 §23: "Do not rely on PostgreSQL-skipped tests as proof
# that protected API behavior works. Where possible, add non-PostgreSQL
# tests for authorization behavior." Checkpoint 12 found a real
# regression (test_risk_api.py/test_universe_api.py/test_strategy_api.py
# never authenticated, hidden because those tests are always
# requires_postgres-skipped in this sandbox). This file provides a
# second, independent, DB-free line of defense against that class of
# regression: it directly introspects each protected view's DRF
# `permission_classes` - no database, no Django test client, no
# @pytest.mark.django_db, runs in every environment unconditionally.
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated

from intraday.infrastructure.api import audit_views, risk_views, strategy_views, universe_views
from intraday.infrastructure.api.permissions import IsConfigurationOperator

READ_VIEWS = (
    risk_views.list_versions,
    risk_views.get_active,
    risk_views.get_version,
    universe_views.list_versions,
    universe_views.get_active,
    universe_views.get_version,
    strategy_views.list_versions,
    strategy_views.get_active,
    strategy_views.get_version,
)

ACTIVATE_VIEWS = (
    risk_views.activate,
    universe_views.activate,
    strategy_views.activate,
)

AUDIT_VIEWS = (
    audit_views.list_risk_configuration_audit,
    audit_views.list_universe_audit,
    audit_views.list_strategy_version_audit,
)


def test_every_read_view_requires_authentication() -> None:
    for view in READ_VIEWS:
        permission_classes = view.cls.permission_classes
        assert permission_classes == [IsAuthenticated], (
            f"{view.__module__}.{view.__name__} must require IsAuthenticated only, "
            f"got {permission_classes}"
        )


def test_every_activate_view_requires_authentication_and_operator_capability() -> None:
    for view in ACTIVATE_VIEWS:
        permission_classes = view.cls.permission_classes
        assert permission_classes == [IsAuthenticated, IsConfigurationOperator], (
            f"{view.__module__}.{view.__name__} must require IsAuthenticated + "
            f"IsConfigurationOperator, got {permission_classes}"
        )


def test_every_audit_view_requires_the_same_operator_capability_as_activation() -> None:
    """The audit read gate must match the activation gate exactly - audit
    visibility is documented as an operator-level capability, not a
    plain-read one (docs/architecture/AUDITABILITY.md)."""
    for view in AUDIT_VIEWS:
        permission_classes = view.cls.permission_classes
        assert permission_classes == [IsAuthenticated, IsConfigurationOperator], (
            f"{view.__module__}.{view.__name__} must require IsAuthenticated + "
            f"IsConfigurationOperator, got {permission_classes}"
        )


def test_activate_and_audit_permission_sets_are_identical_across_all_three_resources() -> None:
    """Guards against future drift where one resource's activate/audit
    gate is loosened or tightened independently of the other two."""
    activate_permission_sets = {tuple(view.cls.permission_classes) for view in ACTIVATE_VIEWS}
    audit_permission_sets = {tuple(view.cls.permission_classes) for view in AUDIT_VIEWS}
    assert len(activate_permission_sets) == 1, "activate views disagree on required permissions"
    assert len(audit_permission_sets) == 1, "audit views disagree on required permissions"
    assert activate_permission_sets == audit_permission_sets
