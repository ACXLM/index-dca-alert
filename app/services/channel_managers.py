import sqlite3
from typing import Protocol
from cryptography.fernet import Fernet

from app.services.credential import decrypt_credential
from app.services.notifications import (
    NotificationContext,
    NotificationResult,
    TelegramChannel,
    TelegramConfig,
)
from app.services.feishu_channel import FeishuChannel, FeishuConfig
from app.repositories.sqlite import UserNotificationEndpointRepository, NotificationRepository, utc_now_iso

class NotificationChannelManager(Protocol):
    channel_type: str

    def dispatch_signal(
        self,
        context: NotificationContext,
        repository: NotificationRepository,
    ) -> list[NotificationResult]: ...

class BaseManager:
    channel_type: str

    def __init__(self, conn: sqlite3.Connection, fernet: Fernet):
        self.conn = conn
        self.fernet = fernet
        self.endpoint_repo = UserNotificationEndpointRepository(conn)

    def dispatch_signal(self, context: NotificationContext, repository: NotificationRepository) -> list[NotificationResult]:
        endpoints = self.endpoint_repo.list_enabled_for_index_and_channel(context.index_name, self.channel_type) # Actually the arg is index_id?
        # Wait, context doesn't have index_id explicitly as a property if we look at it?
        # NotificationContext has `signal_id`, `index_name`. Wait, `daily_run` uses `index_id` somewhere.
        # But we must use `index_id`. Let's get it from the signal via repository.
        # However, to avoid another DB lookup, we might need index_id.
        # Actually `NotificationContext` does not have `index_id`. Let's look at it.
        # But wait, my implementation will just fetch the index_id from valuation_signals.
        row = self.conn.execute("SELECT index_id FROM valuation_signals WHERE id = ?", (context.signal_id,)).fetchone()
        if not row:
            return []
        index_id = row["index_id"]

        endpoints = self.endpoint_repo.list_enabled_for_index_and_channel(index_id, self.channel_type)
        results = []

        for endpoint in endpoints:
            endpoint_id = endpoint["id"]
            if repository.already_sent(context.signal_id, endpoint_id):
                continue
            
            try:
                cred = decrypt_credential(self.fernet, endpoint["credential_enc"])
                channel = self._construct_channel(cred, endpoint["target"])
                res = channel.send(context)
                
                # We need to map `result.target` to endpoint target or just use the target from endpoint
                # Since we changed create_attempt to take endpoint_id instead of target?
                # The result has channel, target, status...
                repository.create_attempt(
                    context.signal_id,
                    self.channel_type,
                    endpoint["target"],
                    res.status,
                    endpoint_id=endpoint_id,
                    error_message=res.error_message,
                    sent_at=res.sent_at
                )
                results.append(res)
            except Exception as e:
                repository.create_attempt(
                    context.signal_id,
                    self.channel_type,
                    endpoint["target"],
                    "failed",
                    endpoint_id=endpoint_id,
                    error_message=str(e),
                )
                results.append(NotificationResult(
                    channel=self.channel_type,
                    target=endpoint["target"],
                    status="failed",
                    message="",
                    error_message=str(e)
                ))
        return results

    def _construct_channel(self, cred: dict, target: str):
        raise NotImplementedError

class TelegramManager(BaseManager):
    channel_type = "telegram"

    def _construct_channel(self, cred: dict, target: str):
        config = TelegramConfig(bot_token=cred["bot_token"], chat_id=target)
        return TelegramChannel(config)

class FeishuManager(BaseManager):
    channel_type = "feishu"

    def _construct_channel(self, cred: dict, target: str):
        config = FeishuConfig(webhook_token=cred["webhook_token"])
        return FeishuChannel(config)
