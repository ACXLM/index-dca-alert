from __future__ import annotations

from pathlib import Path

import pytest

from app.config import IndexConfig
from app.jobs.telegram_smoke import main as telegram_smoke_main
from app.repositories.sqlite import (
    IndexRepository,
    NotificationRepository,
    SignalInput,
    SignalRepository,
    UserSubscriptionInput,
    UserSubscriptionRepository,
    connect,
    initialize_database,
)
from app.services.notifications import (
    NotificationContext,
    NotificationDispatcher,
    NotificationResult,
    SimpleTemplateRenderer,
    TelegramChannel,
    TelegramConfig,
    TelegramRenderer,
    TemplateRenderError,
)


def test_telegram_rendering_from_fixture_signal() -> None:
    text = TelegramRenderer().render(_context())

    assert "指数：沪深300" in text
    assert "日期：2026-05-18" in text
    assert "建议比例：120" in text
    assert "建议金额：1200" in text


def test_missing_optional_signal_fields_render_clearly() -> None:
    text = TelegramRenderer().render(_context(cape_percentile=None, price_percentile=None))

    assert "CAPE百分位：暂无" in text
    assert "价格百分位：暂无" in text


def test_insufficient_history_renders_without_actionable_amount() -> None:
    text = TelegramRenderer().render(
        _context(
            signal_quality="insufficient_history",
            valuation_zone="不可用",
            dca_ratio=0,
            suggested_amount=0,
            composite_percentile=None,
        )
    )

    assert "信号质量：insufficient_history" in text
    assert "综合估值百分位：暂无" in text
    assert "建议金额：0" in text


def test_template_missing_placeholders_raise_clear_errors() -> None:
    renderer = SimpleTemplateRenderer("指数：{{ index_name }} {{ missing_key }}")

    with pytest.raises(TemplateRenderError, match="missing_key"):
        renderer.render({"index_name": "沪深300"})


def test_dca_ratio_percent_is_formatted_from_ratio() -> None:
    text = TelegramRenderer().render(_context(dca_ratio=0.5))

    assert "建议比例：50" in text


def test_telegram_config_loads_from_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("TG_BOT_TOKEN=token-from-dotenv\nTG_CHAT_ID=chat-from-dotenv\n", encoding="utf-8")
    monkeypatch.delenv("TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TG_CHAT_ID", raising=False)

    config = TelegramConfig.from_env(env_path)

    assert config.bot_token == "token-from-dotenv"
    assert config.chat_id == "chat-from-dotenv"


def test_telegram_payload_uses_env_config_without_parse_mode() -> None:
    http_client = _FakeHttpClient(_FakeResponse(status_code=200, text='{"ok": true}'))
    channel = TelegramChannel(
        TelegramConfig(bot_token="secret-token", chat_id="chat-1", timeout_seconds=7),
        http_client=http_client,
    )

    result = channel.send(_context())

    assert result.status == "sent"
    assert http_client.calls[0]["url"] == "https://api.telegram.org/botsecret-token/sendMessage"
    assert http_client.calls[0]["json"]["chat_id"] == "chat-1"
    assert "parse_mode" not in http_client.calls[0]["json"]
    assert http_client.calls[0]["timeout"] == 7


def test_failed_telegram_send_records_sanitized_error_in_database(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    signal_id = _seed_signal(db_path)
    http_client = _FakeHttpClient(
        _FakeResponse(
            status_code=500,
            text="failed https://api.telegram.org/botsecret-token/sendMessage secret-token",
        )
    )

    with connect(db_path) as conn:
        dispatcher = NotificationDispatcher(
            [
                TelegramChannel(
                    TelegramConfig(bot_token="secret-token", chat_id="chat-1"),
                    http_client=http_client,
                )
            ],
            repository=NotificationRepository(conn),
        )
        results = dispatcher.dispatch(_context(signal_id=signal_id))
        row = conn.execute("SELECT * FROM notifications").fetchone()

    assert results[0].status == "failed"
    assert row["status"] == "failed"
    assert row["error_message"] is not None
    assert "secret-token" not in row["error_message"]
    assert "https://api.telegram.org/botsecret-token" not in row["error_message"]
    assert "https://api.telegram.org/bot[redacted]" in row["error_message"]


def test_successful_telegram_send_records_sent_status(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    signal_id = _seed_signal(db_path)

    with connect(db_path) as conn:
        dispatcher = NotificationDispatcher(
            [
                TelegramChannel(
                    TelegramConfig(bot_token="secret-token", chat_id="chat-1"),
                    http_client=_FakeHttpClient(_FakeResponse(status_code=200, text='{"ok": true}')),
                )
            ],
            repository=NotificationRepository(conn),
        )
        results = dispatcher.dispatch(_context(signal_id=signal_id))
        row = conn.execute("SELECT * FROM notifications").fetchone()

    assert results[0].status == "sent"
    assert row["status"] == "sent"
    assert row["sent_at"] is not None
    assert row["error_message"] is None


def test_dispatching_multiple_channels_records_one_attempt_per_channel(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    signal_id = _seed_signal(db_path)

    with connect(db_path) as conn:
        dispatcher = NotificationDispatcher(
            [_FakeChannel("telegram"), _FakeChannel("email")],
            repository=NotificationRepository(conn),
        )
        results = dispatcher.dispatch(_context(signal_id=signal_id))
        rows = conn.execute("SELECT channel, status FROM notifications ORDER BY channel").fetchall()

    assert [result.channel for result in results] == ["telegram", "email"]
    assert [(row["channel"], row["status"]) for row in rows] == [
        ("email", "sent"),
        ("telegram", "sent"),
    ]


def test_telegram_sender_uses_injectable_http_client_without_live_calls() -> None:
    http_client = _FakeHttpClient(_FakeResponse(status_code=200, text='{"ok": true}'))
    channel = TelegramChannel(
        TelegramConfig(bot_token="secret-token", chat_id="chat-1"),
        http_client=http_client,
    )

    channel.send(_context())

    assert len(http_client.calls) == 1


def test_telegram_smoke_dry_run_renders_message(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = telegram_smoke_main(["--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "指数定投提醒" in captured.out
    assert "指数：沪深300" in captured.out


class _FakeResponse:
    def __init__(self, *, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


class _FakeHttpClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    def post(self, url: str, *, json: dict, timeout: int) -> _FakeResponse:
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return self.response


class _FakeChannel:
    def __init__(self, name: str) -> None:
        self.name = name

    def send(self, context: NotificationContext) -> NotificationResult:
        return NotificationResult(
            channel=self.name,
            target=f"{self.name}-target",
            status="sent",
            message="sent",
            sent_at="2026-05-18T00:00:00Z",
        )


def _context(**overrides: object) -> NotificationContext:
    values = {
        "signal_id": "signal-1",
        "index_name": "沪深300",
        "trade_date": "2026-05-18",
        "market": "CN",
        "category": "cn_broad",
        "pe": 12.5,
        "pe_percentile": 25.0,
        "pb": 1.3,
        "pb_percentile": 30.0,
        "cape_percentile": None,
        "dividend_yield_percentile": None,
        "price_percentile": None,
        "composite_percentile": 27.0,
        "signal_quality": "partial",
        "valuation_zone": "合理偏低",
        "base_amount": 1000,
        "dca_ratio": 1.2,
        "suggested_amount": 1200,
    }
    values.update(overrides)
    return NotificationContext(**values)


def _seed_signal(db_path: Path) -> str:
    initialize_database(db_path)
    with connect(db_path) as conn:
        index_repo = IndexRepository(conn)
        index_repo.seed(
            [
                IndexConfig(
                    code="000300",
                    name="沪深300",
                    market="CN",
                    category="cn_broad",
                    currency="CNY",
                    timezone="Asia/Shanghai",
                    primary_provider="akshare_csindex",
                    source_symbol="000300",
                    enabled=True,
                )
            ]
        )
        index_row = index_repo.get_by_code("000300")
        assert index_row is not None
        subscription_id = UserSubscriptionRepository(conn).create(
            UserSubscriptionInput(
                user_id="local",
                index_id=str(index_row["id"]),
                notify_target="chat-1",
            )
        )
        return SignalRepository(conn).upsert(
            SignalInput(
                user_subscription_id=subscription_id,
                index_id=str(index_row["id"]),
                trade_date="2026-05-18",
                signal_quality="partial",
                valuation_zone="合理偏低",
                dca_ratio=1.2,
                suggested_amount=1200,
                message="fixture",
            )
        )
