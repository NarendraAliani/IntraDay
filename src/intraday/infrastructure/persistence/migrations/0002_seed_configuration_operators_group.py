# Checkpoint 11: seeds the `configuration-operators` Group used by
# infrastructure/api/permissions.py's `IsConfigurationOperator` DRF
# permission. A data migration, not a fixture load or a manual `manage.py
# shell` step, so a fresh database always has the group available for an
# administrator to add users to via `manage.py createsuperuser` +
# `manage.py shell`/admin site - no user is added to it here, only the
# group itself is created. Idempotent (`get_or_create`) and reversible
# (removes the group on migrate-back, only if empty - see `reverse_code`).
from __future__ import annotations

from django.db import migrations

GROUP_NAME = "configuration-operators"


def create_operator_group(apps, schema_editor):  # noqa: ANN001, ARG001
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name=GROUP_NAME)


def remove_operator_group(apps, schema_editor):  # noqa: ANN001, ARG001
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=GROUP_NAME, user__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("persistence", "0001_initial"),
        ("auth", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_operator_group, reverse_code=remove_operator_group),
    ]
