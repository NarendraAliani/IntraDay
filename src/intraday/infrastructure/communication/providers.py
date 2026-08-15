# File: src/intraday/infrastructure/communication/providers.py
#
# Checkpoint 37 Part 3/7: concrete `CommunicationProvider` adapters -
# Telegram and Discord, both satisfying `application.services.
# signal_communication.CommunicationProvider` structurally (Protocol,
# no shared base class needed). Each wraps the existing thin HTTP
# clients (Checkpoint 22) rather than reimplementing the wire protocol.
from __future__ import annotations

from dataclasses import dataclass

from intraday.communication.adapters.discord.client import send_discord_message_with_id
from intraday.communication.adapters.telegram.client import send_telegram_message_with_id
from intraday.communication.contracts.signal_communication import CommunicationChannel


def _mask_tail(value: str, visible: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible:
        return "*" * len(value)
    return f"{'*' * (len(value) - visible)}{value[-visible:]}"


@dataclass(frozen=True, slots=True)
class TelegramCommunicationProvider:
    bot_token: str
    channel_id: str
    channel: CommunicationChannel = CommunicationChannel.TELEGRAM
    provider_name: str = "telegram"

    @property
    def destination_masked(self) -> str:
        return _mask_tail(self.channel_id)

    def send(self, text: str) -> tuple[bool, str | None, str | None, str | None, bool]:
        return send_telegram_message_with_id(self.bot_token, self.channel_id, text)


@dataclass(frozen=True, slots=True)
class DiscordCommunicationProvider:
    webhook_url: str
    channel: CommunicationChannel = CommunicationChannel.DISCORD
    provider_name: str = "discord"

    @property
    def destination_masked(self) -> str:
        return _mask_tail(self.webhook_url)

    def send(self, text: str) -> tuple[bool, str | None, str | None, str | None, bool]:
        return send_discord_message_with_id(self.webhook_url, text)
