# Checkpoint 12: adds the durable, append-only control-plane audit
# table. Application-level append-only enforcement lives on the model
# itself (`AuditLogEntry.save()`/`.delete()`, see models.py) — this
# migration only creates the table/index; it does not attempt
# database-level immutability (no trigger/grant revocation), a
# documented limitation (see docs/architecture/AUDITABILITY.md).
from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("persistence", "0002_seed_configuration_operators_group"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLogEntry",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("occurred_at", models.DateTimeField(db_index=True)),
                ("actor_username", models.CharField(max_length=150)),
                ("actor_user_id", models.PositiveIntegerField()),
                ("action", models.CharField(max_length=100)),
                ("resource_type", models.CharField(max_length=50)),
                ("resource_id", models.CharField(max_length=100)),
                ("version_identifier", models.CharField(max_length=100)),
                (
                    "previous_version",
                    models.CharField(blank=True, max_length=100, null=True),
                ),
                (
                    "outcome",
                    models.CharField(
                        choices=[
                            ("activated", "activated"),
                            ("already_active", "already_active"),
                            ("rejected", "rejected"),
                        ],
                        max_length=20,
                    ),
                ),
                ("request_id", models.CharField(max_length=36)),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["resource_type", "resource_id", "occurred_at"],
                        name="persistence_audit_resource_idx",
                    )
                ],
            },
        ),
    ]
