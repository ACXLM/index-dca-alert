from __future__ import annotations

import sqlite3

import pytest
import requests

from app.services.feishu_channel import FeishuChannel, FeishuConfig, FeishuRenderer, sanitize_feishu_error
from app.services.notifications import NotificationContext, TemplateRenderError


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _FakeHttpClient:
    def __init__(self, response_or_exception: object) -> None:
        self.response_or_exception = response_or_exception
        self.last_url: str | None = None
        self.last_json: dict | None = None

    def post(self, url: str, *, json: dict, timeout: int) -> object:
        self.last_url = url
        self.last_json = json
        if isinstance(self.response_or_exception, Exception):
            raise self.response_or_exception
        return self.response_or_exception


@pytest.fixture
def ctx() -> NotificationContext:
    return NotificationContext(
        signal_id="sig1",
        index_name="沪深300",
        trade_date="2023-01-01",
        market="CN",
        category="cn_broad",
        base_amount=1000,
        dca_ratio=1.0,
        suggested_amount=1000,
        signal_quality="complete",
        valuation_zone="合理",
    )


def test_feishu_send_uses_correct_payload_structure(ctx: NotificationContext) -> None:
    client = _FakeHttpClient(_FakeResponse(200))
    config = FeishuConfig(webhook_token="abcdef12-3456-7890-abcd-ef1234567890")
    channel = FeishuChannel(config, http_client=client)

    channel.send(ctx)

    assert client.last_json is not None
    assert client.last_json["msg_type"] == "text"
    assert "text" in client.last_json["content"]
    assert isinstance(client.last_json["content"]["text"], str)


def test_feishu_send_targets_correct_url(ctx: NotificationContext) -> None:
    token = "abcdef12-3456-7890-abcd-ef1234567890"
    client = _FakeHttpClient(_FakeResponse(200))
    channel = FeishuChannel(FeishuConfig(webhook_token=token), http_client=client)

    channel.send(ctx)

    assert client.last_url == f"https://open.feishu.cn/open-apis/bot/v2/hook/{token}"


def test_feishu_target_returns_last_8_chars_only(ctx: NotificationContext) -> None:
    token = "abcdef12-3456-7890-abcd-ef1234567890"
    channel = FeishuChannel(FeishuConfig(webhook_token=token), http_client=_FakeHttpClient(_FakeResponse(200)))

    assert channel.target == f"feishu:hook/{token[-8:]}"
    assert token not in channel.target or len(channel.target) < len(token)


def test_feishu_target_does_not_include_full_token() -> None:
    long_token = "very-long-secret-webhook-token-value-12345678"
    channel = FeishuChannel(FeishuConfig(webhook_token=long_token), http_client=_FakeHttpClient(_FakeResponse(200)))

    assert long_token not in channel.target
    assert channel.target.startswith("feishu:hook/")


def test_feishu_send_returns_failed_on_4xx(ctx: NotificationContext) -> None:
    client = _FakeHttpClient(_FakeResponse(400, "bad request"))
    channel = FeishuChannel(FeishuConfig(webhook_token="token123"), http_client=client)

    result = channel.send(ctx)

    assert result.status == "failed"
    assert result.error_message is not None


def test_feishu_send_returns_failed_on_5xx(ctx: NotificationContext) -> None:
    client = _FakeHttpClient(_FakeResponse(503, "service unavailable"))
    channel = FeishuChannel(FeishuConfig(webhook_token="token123"), http_client=client)

    result = channel.send(ctx)

    assert result.status == "failed"


def test_feishu_send_catches_network_exception(ctx: NotificationContext) -> None:
    client = _FakeHttpClient(requests.ConnectionError("connection refused"))
    channel = FeishuChannel(FeishuConfig(webhook_token="token123"), http_client=client)

    result = channel.send(ctx)

    assert result.status == "failed"
    assert result.error_message is not None


def test_feishu_send_returns_sent_with_timestamp_on_success(ctx: NotificationContext) -> None:
    client = _FakeHttpClient(_FakeResponse(200, '{"code": 0}'))
    channel = FeishuChannel(FeishuConfig(webhook_token="token123"), http_client=client)

    result = channel.send(ctx)

    assert result.status == "sent"
    assert result.sent_at is not None
    assert "T" in result.sent_at


def test_sanitize_feishu_error_removes_token() -> None:
    token = "secret-token-xyz"
    err = f"failed to connect: {token}"

    sanitized = sanitize_feishu_error(err, token)

    assert token not in sanitized
    assert "[redacted]" in sanitized


def test_sanitize_feishu_error_removes_full_webhook_url() -> None:
    token = "secret-token-xyz"
    err = f"POST https://open.feishu.cn/open-apis/bot/v2/hook/{token} failed"

    sanitized = sanitize_feishu_error(err, token)

    assert token not in sanitized
    assert "https://open.feishu.cn/open-apis/bot/v2/hook/[redacted]" in sanitized


def test_feishu_renderer_renders_nonempty_string(ctx: NotificationContext) -> None:
    renderer = FeishuRenderer()

    result = renderer.render(ctx)

    assert isinstance(result, str)
    assert len(result) > 0


def test_feishu_renderer_missing_placeholder_raises_template_render_error() -> None:
    from app.services.notifications import SimpleTemplateRenderer

    bad_renderer = FeishuRenderer(
        template_renderer=SimpleTemplateRenderer("value: {{ missing_key }}")
    )
    ctx = NotificationContext(
        signal_id="s1",
        index_name="Test",
        trade_date="2023-01-01",
        market="CN",
        category="cn_broad",
        base_amount=1000,
        dca_ratio=1.0,
        suggested_amount=1000,
        signal_quality="complete",
        valuation_zone="fair",
    )

    with pytest.raises(TemplateRenderError):
        bad_renderer.render(ctx)


def test_feishu_channel_does_not_require_parse_mode(ctx: NotificationContext) -> None:
    client = _FakeHttpClient(_FakeResponse(200))
    channel = FeishuChannel(FeishuConfig(webhook_token="tok"), http_client=client)

    channel.send(ctx)

    assert "parse_mode" not in (client.last_json or {})
