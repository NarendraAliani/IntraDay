# Checkpoint 22: operational provider settings - Dhan broker
# connectivity, Telegram/Discord notification channels, and a shared
# connection-status table. See infrastructure/persistence/models.py for
# the full field-by-field rationale. Also widens AuditLogEntry.outcome
# with a fourth "updated" value for provider-credential change events
# (a credential save is not a configuration "activation" - there is no
# version - but is still exactly the kind of security-sensitive change
# this audit trail exists to record).
from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('persistence', '0004_rename_persistence_audit_resource_idx_persistence_resourc_b12240_idx'),
    ]

    operations = [
        migrations.CreateModel(
            name='DhanCredential',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('client_id', models.CharField(blank=True, default='', max_length=100)),
                ('encrypted_access_token', models.BinaryField(blank=True, null=True)),
                ('enabled', models.BooleanField(default=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by_username', models.CharField(blank=True, default='', max_length=150)),
            ],
        ),
        migrations.CreateModel(
            name='DiscordCredential',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('encrypted_webhook_url', models.BinaryField(blank=True, null=True)),
                ('enabled', models.BooleanField(default=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by_username', models.CharField(blank=True, default='', max_length=150)),
            ],
        ),
        migrations.CreateModel(
            name='ProviderConnectionStatus',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(choices=[('dhan', 'dhan'), ('telegram', 'telegram'), ('discord', 'discord')], max_length=32, unique=True)),
                ('status', models.CharField(choices=[('NOT_CONFIGURED', 'NOT_CONFIGURED'), ('CONFIGURED', 'CONFIGURED'), ('CONNECTING', 'CONNECTING'), ('CONNECTED', 'CONNECTED'), ('DISCONNECTED', 'DISCONNECTED'), ('AUTHENTICATION_FAILED', 'AUTHENTICATION_FAILED'), ('TOKEN_EXPIRED', 'TOKEN_EXPIRED'), ('CONNECTION_ERROR', 'CONNECTION_ERROR'), ('DISABLED', 'DISABLED')], default='NOT_CONFIGURED', max_length=32)),
                ('last_checked_at', models.DateTimeField(blank=True, null=True)),
                ('last_success_at', models.DateTimeField(blank=True, null=True)),
                ('last_failure_at', models.DateTimeField(blank=True, null=True)),
                ('failure_reason_safe', models.CharField(blank=True, default='', max_length=255)),
                ('latency_ms', models.PositiveIntegerField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='TelegramCredential',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('encrypted_bot_token', models.BinaryField(blank=True, null=True)),
                ('channel_id', models.CharField(blank=True, default='', max_length=100)),
                ('enabled', models.BooleanField(default=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by_username', models.CharField(blank=True, default='', max_length=150)),
            ],
        ),
        migrations.AlterField(
            model_name='auditlogentry',
            name='outcome',
            field=models.CharField(choices=[('activated', 'activated'), ('already_active', 'already_active'), ('rejected', 'rejected'), ('updated', 'updated')], max_length=20),
        ),
    ]
