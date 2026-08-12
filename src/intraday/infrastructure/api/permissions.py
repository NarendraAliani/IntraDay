# File: src/intraday/infrastructure/api/permissions.py
#
# DRF permission classes for the Checkpoint 11 authorization boundary.
# Authorization model: Django's built-in Group mechanism, not a bespoke
# permission table or a new Django app. Two capabilities exist:
#
#   configuration.read     -> any authenticated user (`IsAuthenticated`,
#                              used directly on read views - no class here)
#   configuration.activate -> membership in the `configuration-operators`
#                              Group, or `is_superuser` (`IsConfigurationOperator`)
#
# Chosen over Django's per-model custom-permission mechanism because that
# requires attaching permissions to a concrete model's Meta.permissions -
# there is no natural model owning "may activate configuration" (it's a
# capability over an application-layer action, not a Django model CRUD
# permission). Groups are the standard, simplest Django mechanism for a
# capability that isn't tied to one model, and remain trivially
# extensible (add more groups) if finer-grained roles are needed later.
from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

CONFIGURATION_OPERATOR_GROUP = "configuration-operators"


def user_capabilities(user: AbstractBaseUser | AnonymousUser) -> list[str]:
    """The capability tokens (Checkpoint 11 §5's `configuration.read` /
    `configuration.activate` convention) granted to `user`. Used both by
    `IsConfigurationOperator` and by the `/api/v1/auth/session/` response
    body, so the frontend and the backend's own authorization decision
    are always derived from the exact same logic - never two
    independently-maintained lists that could drift."""
    if not user.is_authenticated:
        return []
    capabilities = ["configuration.read"]
    if is_configuration_operator(user):
        capabilities.append("configuration.activate")
    return capabilities


def is_configuration_operator(user: AbstractBaseUser | AnonymousUser) -> bool:
    if not user.is_authenticated:
        return False
    if getattr(user, "is_superuser", False):
        return True
    groups = getattr(user, "groups", None)
    if groups is None:
        return False
    result: bool = groups.filter(name=CONFIGURATION_OPERATOR_GROUP).exists()
    return result


class IsConfigurationOperator(BasePermission):
    """Grants access only to authenticated users who are members of the
    `configuration-operators` Group (or superusers). Always combined with
    `IsAuthenticated` on the view (DRF ANDs permission classes together),
    so an anonymous request is rejected by `IsAuthenticated` first."""

    message = "You do not have permission to activate configuration."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return is_configuration_operator(request.user)
