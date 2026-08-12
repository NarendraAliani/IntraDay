# tests/unit/test_django_boot.py
#
# Infrastructure smoke test (Checkpoint 4 §15): verifies the Django project
# boots under the testing settings module and Django's own system checks
# pass. Contains no business-logic assertions.
from __future__ import annotations

from django.core.management import call_command


def test_django_check_passes() -> None:
    call_command("check")


def test_settings_module_is_testing() -> None:
    from django.conf import settings

    assert settings.DEBUG is False
    assert settings.TRADING_MODE.value == "RESEARCH"
