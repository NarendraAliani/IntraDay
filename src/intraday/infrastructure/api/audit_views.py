# File: src/intraday/infrastructure/api/audit_views.py
#
# DRF view for the Checkpoint 12 read-only audit API. Scope: risk-
# configuration activation events only (matches the write side - see
# infrastructure/persistence/repositories.py's
# DjangoRiskConfigurationRepository.activate()). No write/update/delete
# operation is exposed anywhere in this module - only `list_for_resource`
# (a GET).
#
# Permission: `IsAuthenticated` + `IsConfigurationOperator`, the SAME
# gate as activation itself, not a separate `audit.read` Group. Audit
# visibility is treated as an operator-level governance capability, not
# a plain-read-user one - an ordinary `configuration.read` user can see
# the current configuration state but not who changed it or when
# (documented decision, see docs/architecture/AUDITABILITY.md).
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


@extend_schema(responses={200: AuditEventResponseSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def list_risk_configuration_audit(request: Request, configuration_id: str) -> Response:
    """Every recorded activation attempt (activated/already_active/
    rejected) for one risk-configuration id, newest first."""
    repository = DjangoAuditRepository()
    events = repository.list_for_resource("risk_configuration", configuration_id)
    return Response([_to_response_dict(event) for event in events])
