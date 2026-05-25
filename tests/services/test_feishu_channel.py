import pytest
from app.services.feishu_channel import FeishuChannel, FeishuConfig, FeishuRenderer, sanitize_feishu_error
from app.services.notifications import NotificationContext, NotificationResult, TemplateRenderError
import requests

class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text

class FakeHttpClient:
    def __init__(self, response_or_exception):
        self.response_or_exception = response_or_exception
        self.last_url = None
        self.last_json = None

    def post(self, url, json, timeout):
        self.last_url = url
        self.last_json = json
        if isinstance(self.response_or_exception, Exception):
            raise self.response_or_exception
        return self.response_or_exception

@pytest.fixture
def dummy_context():
    return NotificationContext(
        signal_id="sig1",
        index_name="CSI300",
        trade_date="2023-01-01",
        market="CN",
        category="broad",
        base_amount=1000,
        dca_ratio=1.0,
        suggested_amount=1000,
        signal_quality="high",
        valuation_zone="low",
    )

def test_feishu_channel_success(dummy_context):
    client = FakeHttpClient(FakeResponse(200, '{"code": 0, "msg": "success"}'))
    config = FeishuConfig(webhook_token="12345678-abcd-efgh-ijkl-1234567890ab")
    channel = FeishuChannel(config, http_client=client)
    
    assert channel.target == "feishu:hook/567890ab"
    
    result = channel.send(dummy_context)
    assert result.status == "sent"
    assert result.sent_at is not None
    
    assert client.last_url == "https://open.feishu.cn/open-apis/bot/v2/hook/12345678-abcd-efgh-ijkl-1234567890ab"
    assert client.last_json["msg_type"] == "text"
    assert "text" in client.last_json["content"]
    assert "CSI300" in client.last_json["content"]["text"]

def test_feishu_channel_4xx(dummy_context):
    client = FakeHttpClient(FakeResponse(400, 'bad request'))
    channel = FeishuChannel(FeishuConfig("token123"), http_client=client)
    result = channel.send(dummy_context)
    assert result.status == "failed"
    assert "bad request" in result.error_message

def test_feishu_channel_network_error(dummy_context):
    client = FakeHttpClient(requests.ConnectionError("timeout"))
    channel = FeishuChannel(FeishuConfig("token123"), http_client=client)
    result = channel.send(dummy_context)
    assert result.status == "failed"
    assert "timeout" in result.error_message

def test_sanitize_feishu_error():
    err = "failed to post to https://open.feishu.cn/open-apis/bot/v2/hook/secret-token-123"
    sanitized = sanitize_feishu_error(err, "secret-token-123")
    assert "secret-token-123" not in sanitized
    assert "https://open.feishu.cn/open-apis/bot/v2/hook/[redacted]" in sanitized

def test_feishu_renderer_missing_placeholder():
    # FeishuRenderer uses SimpleTemplateRenderer. If missing, raises TemplateRenderError
    renderer = FeishuRenderer()
    with pytest.raises(TemplateRenderError):
        # Missing context values that template expects
        ctx = NotificationContext(
            signal_id="sig1",
            index_name="CSI300",
            trade_date="2023-01-01",
            market="CN",
            category="broad",
            base_amount=1000,
            dca_ratio=1.0,
            suggested_amount=1000,
            signal_quality="high",
            valuation_zone="low",
        )
        # Using a raw dict to bypass _telegram_template_values which provides defaults
        renderer.template_renderer.render({"missing_key": "val"})
