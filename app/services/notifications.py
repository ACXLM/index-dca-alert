from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests
from dotenv import load_dotenv

from app.config import PROJECT_ROOT
from app.repositories.sqlite import NotificationRepository, utc_now_iso


DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "templates" / "telegram_signal.md"
DEFAULT_TELEGRAM_TIMEOUT_SECONDS = 10
MISSING_VALUE_TEXT = "暂无"


class NotificationError(RuntimeError):
    pass


class TemplateRenderError(NotificationError):
    pass


@dataclass(frozen=True)
class NotificationContext:
    signal_id: str
    index_name: str
    trade_date: str
    market: str
    category: str
    base_amount: float
    dca_ratio: float
    suggested_amount: float
    signal_quality: str
    valuation_zone: str
    pe: float | None = None
    pe_percentile: float | None = None
    pb: float | None = None
    pb_percentile: float | None = None
    cape_percentile: float | None = None
    dividend_yield_percentile: float | None = None
    price_percentile: float | None = None
    composite_percentile: float | None = None


@dataclass(frozen=True)
class NotificationMessage:
    channel: str
    target: str
    text: str


@dataclass(frozen=True)
class NotificationResult:
    channel: str
    target: str
    status: str
    message: str
    error_message: str | None = None
    sent_at: str | None = None


class NotificationChannel(Protocol):
    name: str

    def send(self, context: NotificationContext) -> NotificationResult:
        ...


class HttpClient(Protocol):
    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        timeout: int,
    ) -> Any:
        ...


class SimpleTemplateRenderer:
    _placeholder_pattern = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")

    def __init__(self, template: str) -> None:
        self.template = template

    @classmethod
    def from_file(cls, path: str | Path = DEFAULT_TEMPLATE_PATH) -> SimpleTemplateRenderer:
        return cls(Path(path).read_text(encoding="utf-8"))

    def render(self, values: dict[str, Any]) -> str:
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in values:
                raise TemplateRenderError(f"missing template value: {key}")
            return _format_template_value(values[key])

        return self._placeholder_pattern.sub(replace, self.template)


class TelegramRenderer:
    def __init__(self, template_renderer: SimpleTemplateRenderer | None = None) -> None:
        self.template_renderer = template_renderer or SimpleTemplateRenderer.from_file()

    def render(self, context: NotificationContext) -> str:
        return self.template_renderer.render(_telegram_template_values(context))


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str
    timeout_seconds: int = DEFAULT_TELEGRAM_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls, env_path: str | Path | None = None) -> TelegramConfig:
        if env_path is not None:
            load_dotenv(dotenv_path=env_path)
        else:
            load_dotenv()
        bot_token = os.environ.get("TG_BOT_TOKEN")
        chat_id = os.environ.get("TG_CHAT_ID")
        if not bot_token:
            raise NotificationError("missing TG_BOT_TOKEN")
        if not chat_id:
            raise NotificationError("missing TG_CHAT_ID")
        return cls(bot_token=bot_token, chat_id=chat_id)


class TelegramChannel:
    name = "telegram"

    def __init__(
        self,
        config: TelegramConfig,
        *,
        renderer: TelegramRenderer | None = None,
        http_client: HttpClient | None = None,
    ) -> None:
        self.config = config
        self.renderer = renderer or TelegramRenderer()
        self.http_client = http_client or requests

    def send(self, context: NotificationContext) -> NotificationResult:
        text = self.renderer.render(context)
        url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"
        payload = {
            "chat_id": self.config.chat_id,
            "text": text,
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
                    target=self.config.chat_id,
                    status="failed",
                    message=text,
                    error_message=sanitize_telegram_error(
                        f"telegram status={response.status_code} response={_response_text(response)}",
                        self.config.bot_token,
                    ),
                )
        except Exception as exc:  # noqa: BLE001 - sender must sanitize all client errors.
            return NotificationResult(
                channel=self.name,
                target=self.config.chat_id,
                status="failed",
                message=text,
                error_message=sanitize_telegram_error(str(exc), self.config.bot_token),
            )

        return NotificationResult(
            channel=self.name,
            target=self.config.chat_id,
            status="sent",
            message=text,
            sent_at=utc_now_iso(),
        )


class NotificationDispatcher:
    def __init__(
        self,
        channels: list[NotificationChannel],
        repository: NotificationRepository | None = None,
    ) -> None:
        self.channels = channels
        self.repository = repository

    def dispatch(self, context: NotificationContext) -> list[NotificationResult]:
        results: list[NotificationResult] = []
        for channel in self.channels:
            result = channel.send(context)
            results.append(result)
            if self.repository is not None:
                self.repository.create_attempt(
                    signal_id=context.signal_id,
                    channel=result.channel,
                    target=result.target,
                    status=result.status,
                    error_message=result.error_message,
                    sent_at=result.sent_at,
                )
        return results


def sanitize_telegram_error(error_message: str, bot_token: str) -> str:
    sanitized = error_message.replace(bot_token, "[redacted]")
    sanitized = re.sub(r"https://api\.telegram\.org/bot[^/\s]+", "https://api.telegram.org/bot[redacted]", sanitized)
    return sanitized


def _telegram_template_values(context: NotificationContext) -> dict[str, Any]:
    return {
        "index_name": context.index_name,
        "trade_date": context.trade_date,
        "market": context.market,
        "category": context.category,
        "pe": context.pe,
        "pe_percentile": context.pe_percentile,
        "pb": context.pb,
        "pb_percentile": context.pb_percentile,
        "cape_percentile": context.cape_percentile,
        "dividend_yield_percentile": context.dividend_yield_percentile,
        "price_percentile": context.price_percentile,
        "composite_percentile": context.composite_percentile,
        "signal_quality": context.signal_quality,
        "valuation_zone": context.valuation_zone,
        "base_amount": context.base_amount,
        "dca_ratio_percent": context.dca_ratio * 100,
        "suggested_amount": context.suggested_amount,
    }


def _format_template_value(value: Any) -> str:
    if value is None:
        return MISSING_VALUE_TEXT
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}"
    return str(value)


def _response_text(response: Any) -> str:
    text = getattr(response, "text", "")
    return str(text)[:500]
