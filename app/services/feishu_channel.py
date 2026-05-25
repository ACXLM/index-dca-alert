import re
import requests
from dataclasses import dataclass
from pathlib import Path

from app.config import PROJECT_ROOT
from app.repositories.sqlite import utc_now_iso
from app.services.notifications import (
    NotificationContext,
    NotificationResult,
    SimpleTemplateRenderer,
    _telegram_template_values,
    _response_text,
    HttpClient
)

DEFAULT_FEISHU_TEMPLATE_PATH = PROJECT_ROOT / "templates" / "feishu_signal.md"

@dataclass(frozen=True)
class FeishuConfig:
    webhook_token: str
    timeout_seconds: int = 10

class FeishuRenderer:
    def __init__(self, template_renderer: SimpleTemplateRenderer | None = None) -> None:
        self.template_renderer = template_renderer or SimpleTemplateRenderer.from_file(DEFAULT_FEISHU_TEMPLATE_PATH)

    def render(self, context: NotificationContext) -> str:
        return self.template_renderer.render(_telegram_template_values(context))

def sanitize_feishu_error(error_message: str, webhook_token: str) -> str:
    sanitized = error_message.replace(webhook_token, "[redacted]")
    sanitized = re.sub(r"https://open\.feishu\.cn/open-apis/bot/v2/hook/[^\s]+", "https://open.feishu.cn/open-apis/bot/v2/hook/[redacted]", sanitized)
    return sanitized

class FeishuChannel:
    name = "feishu"

    def __init__(
        self,
        config: FeishuConfig,
        *,
        renderer: FeishuRenderer | None = None,
        http_client: HttpClient | None = None,
    ) -> None:
        self.config = config
        self.renderer = renderer or FeishuRenderer()
        self.http_client = http_client or requests

    @property
    def target(self) -> str:
        last_chars = self.config.webhook_token[-8:] if len(self.config.webhook_token) >= 8 else self.config.webhook_token
        return f"feishu:hook/{last_chars}"

    def send(self, context: NotificationContext) -> NotificationResult:
        text = self.renderer.render(context)
        url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{self.config.webhook_token}"
        payload = {
            "msg_type": "text",
            "content": {
                "text": text
            }
        }
        try:
            response = self.http_client.post(
                url,
                json=payload,
                timeout=self.config.timeout_seconds,
            )
            if getattr(response, "status_code", 0) >= 400:
                return NotificationResult(
                    channel=self.name,
                    target=self.target,
                    status="failed",
                    message=text,
                    error_message=sanitize_feishu_error(
                        f"feishu status={response.status_code} response={_response_text(response)}",
                        self.config.webhook_token,
                    ),
                )
        except Exception as exc:
            return NotificationResult(
                channel=self.name,
                target=self.target,
                status="failed",
                message=text,
                error_message=sanitize_feishu_error(str(exc), self.config.webhook_token),
            )

        return NotificationResult(
            channel=self.name,
            target=self.target,
            status="sent",
            message=text,
            sent_at=utc_now_iso(),
        )
