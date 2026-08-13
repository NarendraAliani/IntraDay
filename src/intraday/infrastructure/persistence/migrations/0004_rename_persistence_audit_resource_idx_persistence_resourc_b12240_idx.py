# Checkpoint 17.2: a no-op index rename. `AuditLogEntry.Meta.indexes`
# (models.py) never declared an explicit `name=` for its composite
# index, so Django auto-generates one by hashing the app/model/field
# names — the exact hash Django 5.2.17 computes today differs slightly
# from what was stored in migration 0003 (authored against an earlier
# point in this project's Django version). This drift was invisible
# until now: `manage.py makemigrations --check --dry-run` could never
# actually run in any prior checkpoint's sandbox (PostgreSQL was always
# unreachable) — Checkpoint 17.2 is the first checkpoint where it could,
# and it surfaced this. Purely a `RENAME INDEX` at the database level —
# no column, constraint, or data change; the index still covers the
# identical fields (`resource_type`, `resource_id`, `occurred_at`).
from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('persistence', '0003_auditlogentry'),
    ]

    operations = [
        migrations.RenameIndex(
            model_name='auditlogentry',
            new_name='persistence_resourc_b12240_idx',
            old_name='persistence_audit_resource_idx',
        ),
    ]
