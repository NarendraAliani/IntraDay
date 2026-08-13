# File: src/intraday/infrastructure/api/audit_views.py
#
# DRF views for the read-only audit API. Scope: risk-configuration
# (Checkpoint 12), universe, and strategy-version (Checkpoint 13)
# activation events. No write/update/delete operation is exposed
# anywhere in this module - only `list_for_resource` (a GET).
#
# One resource-specific endpoint per resource type - NOT a single
# generic `/api/v1/audit/{resource_type}/{resource_id}/` route. A
# fully-generic route would let a caller pass an arbitrary
# `resource_type` string with no OpenAPI-level documentation of which
# values are actually valid, and would blur the same per-resource
# clarity the rest of this API deliberately keeps (Checkpoint 8 §7 - the
# configuration endpoints are also resource-specific, not
# `/api/v1/config/{resource_type}/...`). The three view functions below
# share one private helper (`_list_audit`) to avoid duplicating the
# response-shaping logic - explicitness over premature genericization,
# per the checkpoint brief's own guidance.
#
# Permission: `IsAuthenticated` + `IsConfigurationOperator`, the SAME
# gate as activation itself, not a separate `audit.read` Group - for all
# three resource types. Audit visibility is treated as an operator-level
# governance capability, not a plain-read-user one (documented decision,
# see docs/architecture/AUDITABILITY.md).
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.contracts.audit import AuditEventResponseSerializer
from intraday.control_plane.audit.events import AuditEvent
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.persistence.repositories import DjangoAuditRepository


def _to_response_dict(event: AuditEvent) -> dict[str, object]:
    return {
        "actor": event.actor,
        "action": event.action,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "version": event.version,
        "previous_version": event.previous_version,
        "outcome": event.outcome.value,
        "occurred_at": event.occurred_at,
        "request_id": event.request_id,
    }


def _list_audit(resource_type: str, resource_id: str) -> Response:
    repository = DjangoAuditRepository()
    events = repository.list_for_resource(resource_type, resource_id)
    return Response([_to_response_dict(event) for event in events])


@extend_schema(responses={200: AuditEventResponseSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def list_risk_configuration_audit(request: Request, configuration_id: str) -> Response:
    """Every recorded activation attempt (activated/already_active/
    rejected) for one risk-configuration id, newest first."""
    return _list_audit("risk_configuration", configuration_id)


@extend_schema(responses={200: AuditEventResponseSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def list_universe_audit(request: Request, universe_id: str) -> Response:
    """Every recorded activation attempt for one universe id, newest first."""
    return _list_audit("universe", universe_id)


@extend_schema(responses={200: AuditEventResponseSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def list_strategy_version_audit(request: Request, strategy_id: str) -> Response:
    """Every recorded activation attempt for one strategy id, newest
    first. `version` on each event is the flattened
    `"{specification_version}:{code_version}:{configuration_version}"`
    identifier (see `DjangoStrategyVersionRepository.activate()`)."""
    return _list_audit("strategy_version", strategy_id)
