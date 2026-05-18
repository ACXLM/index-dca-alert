from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.config import AppConfig, IndexConfig, RulesConfig, ZoneRule
from app.jobs.daily_run import is_market_window_open, market_trade_date, run_daily
from app.providers.base import ProviderError, ProviderResult, ProviderValuation
from app.repositories.sqlite import MarketRunRepository, connect, initialize_database
from app.services.notifications import NotificationContext, NotificationResult


def test_cn_market_window_opens_after_local_close() -> None:
    assert is_market_window_open("CN", datetime(2026, 5, 18, 8, 31, tzinfo=UTC)) is True
    assert is_market_window_open("CN", datetime(2026, 5, 18, 8, 0, tzinfo=UTC)) is False


def test_hk_market_window_uses_hong_kong_time() -> None:
    assert is_market_window_open("HK", datetime(2026, 5, 18, 8, 31, tzinfo=UTC)) is True


def test_us_market_window_handles_dst_and_standard_time() -> None:
    assert is_market_window_open("US", datetime(2026, 7, 1, 20, 31, tzinfo=UTC)) is True
    assert is_market_window_open("US", datetime(2026, 1, 5, 21, 31, tzinfo=UTC)) is True
    assert is_market_window_open("US", datetime(2026, 1, 5, 21, 0, tzinfo=UTC)) is False


def test_weekend_market_window_is_closed() -> None:
    assert is_market_window_open("CN", datetime(2026, 5, 17, 8, 31, tzinfo=UTC)) is False


def test_trade_date_uses_market_local_date() -> None:
    assert market_trade_date("US", datetime(2026, 1, 6, 2, 0, tzinfo=UTC)) == "2026-01-05"


def test_unknown_market_raises_clear_error() -> None:
    with pytest.raises(ValueError, match="unsupported market"):
        is_market_window_open("EU", datetime(2026, 5, 18, 8, 31, tzinfo=UTC))


def test_closed_market_skips_without_writing_market_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "index_dca.sqlite"

    result = run_daily(
        db_path=db_path,
        market="CN",
        run_type="primary",
        app_config=_app_config([_index("000300")]),
        providers={"akshare_csindex": _HistoryProvider("2026-05-18")},
        now=datetime(2026, 5, 18, 8, 0, tzinfo=UTC),
    )

    captured = capsys.readouterr()
    assert result.status == "skipped"
    assert result.skipped_reason == "market_window_closed"
    assert "skipped" in captured.out
    assert not db_path.exists()


def test_successful_market_date_skips_fallback_without_new_run_row(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    initialize_database(db_path)
    with connect(db_path) as conn:
        MarketRunRepository(conn).upsert_run("CN", "2026-05-18", "primary", "success")

    result = run_daily(
        db_path=db_path,
        market="CN",
        trade_date="2026-05-18",
        run_type="fallback",
        app_config=_app_config([_index("000300")]),
        providers={"akshare_csindex": _HistoryProvider("2026-05-18")},
        now=datetime(2026, 5, 18, 8, 31, tzinfo=UTC),
    )

    with connect(db_path) as conn:
        fallback = MarketRunRepository(conn).get_run("CN", "2026-05-18", "fallback")

    assert result.status == "skipped"
    assert result.skipped_reason == "already_succeeded"
    assert fallback is None


def test_force_bypasses_successful_market_date_guard(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    initialize_database(db_path)
    with connect(db_path) as conn:
        MarketRunRepository(conn).upsert_run("CN", "2026-05-18", "primary", "success")

    result = run_daily(
        db_path=db_path,
        market="CN",
        trade_date="2026-05-18",
        run_type="fallback",
        force=True,
        app_config=_app_config([_index("000300")]),
        providers={"akshare_csindex": _HistoryProvider("2026-05-18")},
        env={},
        now=datetime(2026, 5, 18, 8, 31, tzinfo=UTC),
    )

    with connect(db_path) as conn:
        fallback = MarketRunRepository(conn).get_run("CN", "2026-05-18", "fallback")

    assert result.status == "success"
    assert fallback is not None
    assert fallback["status"] == "success"


def test_force_bypasses_market_window_check(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"

    result = run_daily(
        db_path=db_path,
        market="CN",
        trade_date="2026-05-18",
        force=True,
        app_config=_app_config([_index("000300")]),
        providers={"akshare_csindex": _HistoryProvider("2026-05-18")},
        env={},
        now=datetime(2026, 5, 18, 8, 0, tzinfo=UTC),
    )

    assert result.status == "success"


def test_daily_run_persists_signal_without_telegram_config(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"

    result = run_daily(
        db_path=db_path,
        market="CN",
        trade_date="2026-05-18",
        app_config=_app_config([_index("000300", name="沪深300")]),
        providers={"akshare_csindex": _HistoryProvider("2026-05-18")},
        env={},
        now=datetime(2026, 5, 18, 8, 31, tzinfo=UTC),
    )

    with connect(db_path) as conn:
        signal = conn.execute("SELECT * FROM valuation_signals").fetchone()
        subscription = conn.execute("SELECT * FROM user_subscriptions").fetchone()
        notifications = conn.execute("SELECT COUNT(*) AS count FROM notifications").fetchone()
        market_run = MarketRunRepository(conn).get_run("CN", "2026-05-18", "primary")

    assert result.status == "success"
    assert signal is not None
    assert signal["signal_quality"] == "complete"
    assert signal["composite_percentile"] is not None
    assert subscription["notify_target"] == "local-disabled"
    assert notifications["count"] == 0
    assert market_run is not None
    assert market_run["status"] == "success"


def test_daily_run_bootstraps_telegram_subscription_and_records_notification(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    channel = _FakeChannel("telegram")

    result = run_daily(
        db_path=db_path,
        market="CN",
        trade_date="2026-05-18",
        app_config=_app_config([_index("000300", name="沪深300")]),
        providers={"akshare_csindex": _HistoryProvider("2026-05-18")},
        notification_channels=[channel],
        env={"TG_BOT_TOKEN": "token", "TG_CHAT_ID": "chat-1"},
        now=datetime(2026, 5, 18, 8, 31, tzinfo=UTC),
    )

    with connect(db_path) as conn:
        subscription = conn.execute("SELECT * FROM user_subscriptions").fetchone()
        notification = conn.execute("SELECT * FROM notifications").fetchone()

    assert result.status == "success"
    assert result.notifications_sent == 1
    assert subscription["notify_target"] == "chat-1"
    assert notification["status"] == "sent"
    assert channel.contexts[0].index_name == "沪深300"


def test_dry_run_does_not_record_notification_attempts(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    channel = _FakeChannel("telegram")

    result = run_daily(
        db_path=db_path,
        market="CN",
        trade_date="2026-05-18",
        dry_run=True,
        app_config=_app_config([_index("000300")]),
        providers={"akshare_csindex": _HistoryProvider("2026-05-18")},
        notification_channels=[channel],
        env={"TG_BOT_TOKEN": "token", "TG_CHAT_ID": "chat-1"},
        now=datetime(2026, 5, 18, 8, 31, tzinfo=UTC),
    )

    with connect(db_path) as conn:
        notification_count = conn.execute("SELECT COUNT(*) AS count FROM notifications").fetchone()["count"]

    assert result.status == "success"
    assert result.notifications_sent == 0
    assert notification_count == 0
    assert channel.contexts == []


def test_one_index_provider_failure_does_not_block_other_index(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"

    result = run_daily(
        db_path=db_path,
        market="CN",
        trade_date="2026-05-18",
        app_config=_app_config([_index("000300"), _index("000905")]),
        providers={"akshare_csindex": _MixedProvider("2026-05-18")},
        env={},
        now=datetime(2026, 5, 18, 8, 31, tzinfo=UTC),
    )

    with connect(db_path) as conn:
        signal_count = conn.execute("SELECT COUNT(*) AS count FROM valuation_signals").fetchone()["count"]
        event = conn.execute("SELECT * FROM data_quality_events WHERE event_type = 'provider_failure'").fetchone()

    assert result.status == "success"
    assert result.processed_indices == 2
    assert signal_count == 1
    assert event is not None


def test_all_failed_indices_mark_market_run_failed(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"

    result = run_daily(
        db_path=db_path,
        market="CN",
        trade_date="2026-05-18",
        app_config=_app_config([_index("000300")]),
        providers={"akshare_csindex": _FailingProvider()},
        env={},
        now=datetime(2026, 5, 18, 8, 31, tzinfo=UTC),
    )

    with connect(db_path) as conn:
        market_run = MarketRunRepository(conn).get_run("CN", "2026-05-18", "primary")

    assert result.status == "failed"
    assert market_run is not None
    assert market_run["status"] == "failed"
    assert "no usable valuation data" in market_run["error_message"]


def test_unexpected_boundary_failure_records_failed_market_run(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"

    result = run_daily(
        db_path=db_path,
        market="CN",
        trade_date="2026-05-18",
        app_config=_app_config([_index("000300")]),
        providers={"akshare_csindex": _BrokenProvider()},
        env={},
        now=datetime(2026, 5, 18, 8, 31, tzinfo=UTC),
    )

    with connect(db_path) as conn:
        market_run = MarketRunRepository(conn).get_run("CN", "2026-05-18", "primary")

    assert result.status == "failed"
    assert market_run is not None
    assert market_run["status"] == "failed"
    assert "unexpected provider error" in market_run["error_message"]


def test_workflow_uses_uv_and_no_requirements_install() -> None:
    workflow = Path(".github/workflows/index-dca-alert.yml").read_text(encoding="utf-8")

    assert "uv sync --frozen" in workflow
    assert "uv run python -m app.jobs.daily_run" in workflow
    assert "pip install -r requirements.txt" not in workflow
    assert "git diff --cached --quiet" in workflow


class _HistoryProvider:
    def __init__(self, trade_date: str) -> None:
        self.trade_date = trade_date

    def fetch_history(self, index: IndexConfig, start_date: str, end_date: str) -> ProviderResult:
        return ProviderResult(
            valuations=_valuations_until(self.trade_date),
            issues=[],
        )


class _MixedProvider:
    def __init__(self, trade_date: str) -> None:
        self.trade_date = trade_date

    def fetch_history(self, index: IndexConfig, start_date: str, end_date: str) -> ProviderResult:
        if index.code == "000905":
            raise ProviderError("akshare_csindex", index.source_symbol, "provider unavailable")
        return ProviderResult(valuations=_valuations_until(self.trade_date), issues=[])


class _FailingProvider:
    def fetch_history(self, index: IndexConfig, start_date: str, end_date: str) -> ProviderResult:
        raise ProviderError("akshare_csindex", index.source_symbol, "provider unavailable")


class _BrokenProvider:
    def fetch_history(self, index: IndexConfig, start_date: str, end_date: str) -> ProviderResult:
        raise RuntimeError("unexpected provider error")


class _FakeChannel:
    def __init__(self, name: str) -> None:
        self.name = name
        self.contexts: list[NotificationContext] = []

    def send(self, context: NotificationContext) -> NotificationResult:
        self.contexts.append(context)
        return NotificationResult(
            channel=self.name,
            target=f"{self.name}-target",
            status="sent",
            message="sent",
            sent_at="2026-05-18T00:00:00Z",
        )


def _valuations_until(trade_date: str) -> list[ProviderValuation]:
    current = date.fromisoformat(trade_date)
    values = [(10.0, 1.0), (11.0, 1.1), (12.0, 1.2)]
    valuations = []
    for offset, (pe, pb) in zip(range(2, -1, -1), values, strict=True):
        day = current - timedelta(days=offset)
        valuations.append(
            ProviderValuation(
                trade_date=day.isoformat(),
                pe=pe,
                pb=pb,
                source="akshare_csindex",
                source_type="native_index",
                metric_schema_version="v1",
                raw_json={"date": day.isoformat()},
            )
        )
    return valuations


def _app_config(indices: list[IndexConfig]) -> AppConfig:
    return AppConfig(indices=indices, rules=_rules())


def _index(code: str, *, name: str | None = None) -> IndexConfig:
    return IndexConfig(
        code=code,
        name=name or code,
        enabled=True,
        market="CN",
        category="cn_broad",
        currency="CNY",
        timezone="Asia/Shanghai",
        primary_provider="akshare_csindex",
        source_symbol=code,
    )


def _rules() -> RulesConfig:
    return RulesConfig(
        lookback_years=5,
        minimum_observations=3,
        base_amount=1000,
        metric_weights={"cn_broad": {"pe": 0.6, "pb": 0.4}},
        zone_rules=[
            ZoneRule(min=0, max=15, zone="明显低估", dca_ratio=2.0),
            ZoneRule(min=15, max=30, zone="合理偏低", dca_ratio=1.2),
            ZoneRule(min=30, max=60, zone="合理", dca_ratio=1.0),
            ZoneRule(min=60, max=80, zone="合理偏高", dca_ratio=0.5),
            ZoneRule(min=80, max=100, zone="高估", dca_ratio=0.0),
        ],
    )
