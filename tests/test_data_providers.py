from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from app.config import AppConfig, IndexConfig, RulesConfig, ZoneRule
from app.jobs.backfill import run_backfill
from app.providers.akshare_csindex import (
    LEGULEGU_METRIC_SCHEMA_VERSION,
    LEGULEGU_SOURCE,
    METRIC_SCHEMA_VERSION,
    SOURCE,
    SOURCE_TYPE,
    AkshareCsindexProvider,
    normalize_legulegu_index_rows,
    normalize_akshare_csindex_rows,
)
from app.providers.base import ProviderError, ProviderResult, ProviderRowIssue, ProviderValuation
from app.repositories.sqlite import connect


def test_akshare_csi_normalization_maps_fixture_fields() -> None:
    result = normalize_akshare_csindex_rows(
        [
            {
                "日期": "2026-05-15",
                "市盈率": "12.5",
                "市净率": "1.4",
                "股息率": "2.1",
                "收盘": "3900",
            }
        ],
        start_date="2026-01-01",
        end_date="2026-12-31",
    )

    assert result.issues == []
    valuation = result.valuations[0]
    assert valuation.trade_date == "2026-05-15"
    assert valuation.pe == 12.5
    assert valuation.pb == 1.4
    assert valuation.dividend_yield == 2.1
    assert valuation.close == 3900
    assert valuation.source == SOURCE
    assert valuation.source_type == SOURCE_TYPE
    assert valuation.metric_schema_version == METRIC_SCHEMA_VERSION


def test_akshare_raw_json_is_safe_when_trade_date_is_date_object(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    provider = AkshareCsindexProvider(
        client=_AkshareClient(
            [
                {
                    "日期": date(2026, 5, 15),
                    "市盈率": "12.5",
                    "市净率": "1.4",
                }
            ]
        )
    )

    run_backfill(
        db_path=db_path,
        app_config=_app_config(indices=[_index("H30374")]),
        providers={"akshare_csindex": provider},
        today=date(2026, 5, 17),
    )

    with connect(db_path) as conn:
        row = conn.execute("SELECT trade_date, raw_json FROM index_valuations").fetchone()

    assert row["trade_date"] == "2026-05-15"
    assert '"日期": "2026-05-15"' in row["raw_json"]


def test_legulegu_normalization_merges_pe_pb_for_5_year_history() -> None:
    result = normalize_legulegu_index_rows(
        pe_rows=[
            {"日期": "2021-05-17", "滚动市盈率": 14.2, "指数": 5100},
            {"日期": "2026-05-15", "滚动市盈率": 12.5, "指数": 3900},
        ],
        pb_rows=[
            {"日期": "2021-05-17", "市净率": 1.5},
            {"日期": "2026-05-15", "市净率": 1.3},
        ],
        start_date="2021-05-17",
        end_date="2026-05-17",
    )

    assert len(result.valuations) == 2
    assert result.valuations[0].trade_date == "2021-05-17"
    assert result.valuations[0].pe == 14.2
    assert result.valuations[0].pb == 1.5
    assert result.valuations[0].close == 5100
    assert result.valuations[0].source == LEGULEGU_SOURCE
    assert result.valuations[0].source_type == SOURCE_TYPE
    assert result.valuations[0].metric_schema_version == LEGULEGU_METRIC_SCHEMA_VERSION


def test_cn_akshare_provider_uses_legulegu_history_not_recent_csindex_rows() -> None:
    provider = AkshareCsindexProvider(client=_AkshareClientWithLegulegu())

    result = provider.fetch_history(_index("000300"), "2021-05-17", "2026-05-17")

    assert len(result.valuations) == 2
    assert result.valuations[0].trade_date == "2021-05-17"
    assert {valuation.source for valuation in result.valuations} == {LEGULEGU_SOURCE}


def test_cn_akshare_provider_rejects_recent_only_history() -> None:
    provider = AkshareCsindexProvider(client=_RecentOnlyAkshareClient())

    with pytest.raises(ProviderError, match="insufficient valuation history coverage"):
        provider.fetch_history(_index("000300"), "2021-05-17", "2026-05-17")


def test_backfill_does_not_write_recent_only_cn_history(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"

    result = run_backfill(
        db_path=db_path,
        app_config=_app_config(indices=[_index("000300")]),
        providers={"akshare_csindex": AkshareCsindexProvider(client=_RecentOnlyAkshareClient())},
        years=5,
        today=date(2026, 5, 17),
    )

    with connect(db_path) as conn:
        valuation_count = conn.execute("SELECT COUNT(*) AS count FROM index_valuations").fetchone()["count"]
        event = conn.execute("SELECT * FROM data_quality_events").fetchone()

    assert result.inserted_or_updated_rows == 0
    assert valuation_count == 0
    assert event["event_type"] == "provider_failure"
    assert "insufficient valuation history coverage" in event["message"]


def test_backfill_writes_5_year_legulegu_history_when_csindex_is_recent_only(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"

    run_backfill(
        db_path=db_path,
        app_config=_app_config(indices=[_index("000300")]),
        providers={"akshare_csindex": AkshareCsindexProvider(client=_AkshareClientWithLegulegu())},
        years=5,
        today=date(2026, 5, 17),
    )

    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count, MIN(trade_date) AS first_date, MAX(trade_date) AS last_date
            FROM index_valuations
            """
        ).fetchone()

    assert row["count"] == 2
    assert row["first_date"] == "2021-05-17"
    assert row["last_date"] == "2026-05-15"


def test_missing_optional_fields_are_none_not_zero() -> None:
    result = normalize_akshare_csindex_rows(
        [{"日期": "2026-05-15", "市盈率": "12.5", "市净率": "", "股息率": "-", "收盘": "--"}],
        start_date="2026-01-01",
        end_date="2026-12-31",
    )

    valuation = result.valuations[0]
    assert valuation.pe == 12.5
    assert valuation.pb is None
    assert valuation.dividend_yield is None
    assert valuation.close is None


def test_invalid_rows_are_reported_without_valid_valuations() -> None:
    result = normalize_akshare_csindex_rows(
        [
            {"市盈率": "12.5"},
            {"日期": "2026-05-15", "市盈率": "", "市净率": None, "收盘": "-"},
        ],
        start_date="2026-01-01",
        end_date="2026-12-31",
    )

    assert result.valuations == []
    assert [issue.event_type for issue in result.issues] == [
        "missing_required_field",
        "invalid_row",
    ]


def test_provider_failures_raise_provider_error() -> None:
    class BrokenClient:
        def stock_index_pe_lg(self, symbol: str) -> object:
            raise RuntimeError(f"boom {symbol}")

        def stock_index_pb_lg(self, symbol: str) -> object:
            raise RuntimeError(f"boom {symbol}")

    provider = AkshareCsindexProvider(client=BrokenClient())

    with pytest.raises(ProviderError, match="boom 沪深300"):
        provider.fetch_history(_index("000300"), "2026-01-01", "2026-12-31")


def test_provider_adapter_does_not_write_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    result = normalize_akshare_csindex_rows(
        [{"日期": "2026-05-15", "市盈率": "12.5"}],
        start_date="2026-01-01",
        end_date="2026-12-31",
    )

    assert result.valuations
    assert not db_path.exists()


def test_backfill_is_idempotent_and_preserves_source_metadata(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    config = _app_config(indices=[_index("000300")])
    providers = {"akshare_csindex": _FixtureProvider(_provider_result("2026-05-15"))}

    first = run_backfill(
        db_path=db_path,
        app_config=config,
        providers=providers,
        today=date(2026, 5, 17),
    )
    second = run_backfill(
        db_path=db_path,
        app_config=config,
        providers=providers,
        today=date(2026, 5, 17),
    )

    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM index_valuations").fetchall()

    assert first.inserted_or_updated_rows == 1
    assert second.inserted_or_updated_rows == 1
    assert len(rows) == 1
    assert rows[0]["source"] == SOURCE
    assert rows[0]["source_type"] == SOURCE_TYPE
    assert rows[0]["metric_schema_version"] == METRIC_SCHEMA_VERSION


def test_backfill_skips_provider_when_requested_window_is_cached(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    config = _app_config(indices=[_index("000300")])
    provider = _FixtureProvider(_provider_result_many(["2025-05-15", "2026-05-15"]))

    first = run_backfill(
        db_path=db_path,
        app_config=config,
        providers={"akshare_csindex": provider},
        years=1,
        today=date(2026, 5, 15),
    )
    second = run_backfill(
        db_path=db_path,
        app_config=config,
        providers={"akshare_csindex": provider},
        years=1,
        today=date(2026, 5, 15),
    )

    assert first.skipped_indices == 0
    assert second.skipped_indices == 1
    assert provider.calls == [("000300", "2025-05-15", "2026-05-15")]


def test_backfill_refresh_bypasses_cached_window(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    config = _app_config(indices=[_index("000300")])
    provider = _FixtureProvider(_provider_result_many(["2025-05-15", "2026-05-15"]))

    run_backfill(
        db_path=db_path,
        app_config=config,
        providers={"akshare_csindex": provider},
        years=1,
        today=date(2026, 5, 15),
    )
    result = run_backfill(
        db_path=db_path,
        app_config=config,
        providers={"akshare_csindex": provider},
        years=1,
        today=date(2026, 5, 15),
        refresh=True,
    )

    assert result.skipped_indices == 0
    assert provider.calls == [
        ("000300", "2025-05-15", "2026-05-15"),
        ("000300", "2025-05-15", "2026-05-15"),
    ]


def test_backfill_records_coverage_gaps(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    config = _app_config(indices=[_index("000300")])
    providers = {"akshare_csindex": _FixtureProvider(_provider_result("2026-05-15"))}

    run_backfill(
        db_path=db_path,
        app_config=config,
        providers=providers,
        years=5,
        today=date(2026, 5, 17),
    )

    with connect(db_path) as conn:
        events = conn.execute(
            "SELECT event_type FROM data_quality_events ORDER BY created_at"
        ).fetchall()

    assert "coverage_gap" in [event["event_type"] for event in events]


def test_backfill_records_provider_failures(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    config = _app_config(indices=[_index("000300")])
    providers = {"akshare_csindex": _FailingProvider()}

    result = run_backfill(
        db_path=db_path,
        app_config=config,
        providers=providers,
        today=date(2026, 5, 17),
    )

    with connect(db_path) as conn:
        event = conn.execute("SELECT * FROM data_quality_events").fetchone()

    assert result.processed_indices == 1
    assert result.inserted_or_updated_rows == 0
    assert event["event_type"] == "provider_failure"


def test_backfill_records_invalid_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    config = _app_config(indices=[_index("000300")])
    providers = {
        "akshare_csindex": _FixtureProvider(
            ProviderResult(
                valuations=[],
                issues=[
                    ProviderRowIssue(
                        event_type="invalid_row",
                        message="bad row",
                        trade_date="2026-05-15",
                    )
                ],
            )
        )
    }

    run_backfill(
        db_path=db_path,
        app_config=config,
        providers=providers,
        today=date(2026, 5, 17),
    )

    with connect(db_path) as conn:
        valuation_count = conn.execute("SELECT COUNT(*) AS count FROM index_valuations").fetchone()["count"]
        event = conn.execute("SELECT * FROM data_quality_events").fetchone()

    assert valuation_count == 0
    assert event["event_type"] == "invalid_row"


def test_backfill_initializes_and_seeds_before_writing_valuations(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    config = _app_config(indices=[_index("000300")])

    run_backfill(
        db_path=db_path,
        app_config=config,
        providers={"akshare_csindex": _FixtureProvider(_provider_result("2026-05-15"))},
        today=date(2026, 5, 17),
    )

    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) AS count FROM indices").fetchone()["count"] == 1
        assert conn.execute("SELECT COUNT(*) AS count FROM dca_rules").fetchone()["count"] == 1
        assert conn.execute("SELECT COUNT(*) AS count FROM index_valuations").fetchone()["count"] == 1


def test_backfill_applies_filters_and_db_path(tmp_path: Path) -> None:
    db_path = tmp_path / "filtered.sqlite"
    indices = [_index("000300"), _index("000905"), _index("HSI", market="HK", provider="missing")]
    config = _app_config(indices=indices)
    provider = _FixtureProvider(_provider_result("2026-05-15"))

    result = run_backfill(
        db_path=db_path,
        app_config=config,
        providers={"akshare_csindex": provider},
        years=1,
        market="CN",
        index_code="000905",
        today=date(2026, 5, 17),
    )

    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT indices.code, index_valuations.trade_date
            FROM index_valuations
            JOIN indices ON indices.id = index_valuations.index_id
            """
        ).fetchall()

    assert db_path.exists()
    assert result.processed_indices == 1
    assert provider.calls == [("000905", "2025-05-17", "2026-05-17")]
    assert [(row["code"], row["trade_date"]) for row in rows] == [("000905", "2026-05-15")]


def test_backfill_does_not_call_signal_or_notification_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("signal calculation should not be called")

    monkeypatch.setattr(
        "app.services.valuation_signals.calculate_signal",
        fail_if_called,
    )

    run_backfill(
        db_path=tmp_path / "index_dca.sqlite",
        app_config=_app_config(indices=[_index("000300")]),
        providers={"akshare_csindex": _FixtureProvider(_provider_result("2026-05-15"))},
        today=date(2026, 5, 17),
    )


def test_one_index_provider_failure_does_not_remove_committed_rows_for_another(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    config = _app_config(indices=[_index("000300"), _index("000905")])
    provider = _MixedProvider()

    run_backfill(
        db_path=db_path,
        app_config=config,
        providers={"akshare_csindex": provider},
        today=date(2026, 5, 17),
    )

    with connect(db_path) as conn:
        valuation_codes = [
            row["code"]
            for row in conn.execute(
                """
                SELECT indices.code
                FROM index_valuations
                JOIN indices ON indices.id = index_valuations.index_id
                """
            ).fetchall()
        ]
        event = conn.execute("SELECT * FROM data_quality_events WHERE event_type = 'provider_failure'").fetchone()

    assert valuation_codes == ["000300"]
    assert event is not None


class _FixtureProvider:
    def __init__(self, result: ProviderResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str, str]] = []

    def fetch_history(self, index: IndexConfig, start_date: str, end_date: str) -> ProviderResult:
        self.calls.append((index.code, start_date, end_date))
        return self.result


class _AkshareClient:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def stock_zh_index_value_csindex(self, symbol: str) -> list[dict]:
        return self.rows


class _AkshareClientWithLegulegu:
    def stock_zh_index_value_csindex(self, symbol: str) -> list[dict]:
        return [
            {
                "日期": date(2026, 5, 15),
                "市盈率": "12.5",
                "市净率": "1.4",
            }
        ]

    def stock_index_pe_lg(self, symbol: str) -> list[dict]:
        return [
            {"日期": date(2021, 5, 17), "滚动市盈率": 15.0, "指数": 5000},
            {"日期": date(2026, 5, 15), "滚动市盈率": 12.5, "指数": 3900},
        ]

    def stock_index_pb_lg(self, symbol: str) -> list[dict]:
        return [
            {"日期": date(2021, 5, 17), "市净率": 1.5},
            {"日期": date(2026, 5, 15), "市净率": 1.3},
        ]


class _RecentOnlyAkshareClient:
    def stock_zh_index_value_csindex(self, symbol: str) -> list[dict]:
        return [
            {
                "日期": date(2026, 5, 15),
                "市盈率": "12.5",
                "市净率": "1.4",
            }
        ]

    def stock_index_pe_lg(self, symbol: str) -> list[dict]:
        return [
            {"日期": date(2026, 5, 15), "滚动市盈率": 12.5, "指数": 3900},
        ]

    def stock_index_pb_lg(self, symbol: str) -> list[dict]:
        return [
            {"日期": date(2026, 5, 15), "市净率": 1.3},
        ]


class _FailingProvider:
    def fetch_history(self, index: IndexConfig, start_date: str, end_date: str) -> ProviderResult:
        raise ProviderError("akshare_csindex", index.source_symbol, "provider unavailable")


class _MixedProvider:
    def fetch_history(self, index: IndexConfig, start_date: str, end_date: str) -> ProviderResult:
        if index.code == "000905":
            raise ProviderError("akshare_csindex", index.source_symbol, "provider unavailable")
        return _provider_result("2026-05-15")


def _provider_result(trade_date: str) -> ProviderResult:
    return _provider_result_many([trade_date])


def _provider_result_many(trade_dates: list[str]) -> ProviderResult:
    return ProviderResult(
        valuations=[
            ProviderValuation(
                trade_date=trade_date,
                pe=12.0,
                pb=1.2,
                source=SOURCE,
                source_type=SOURCE_TYPE,
                metric_schema_version=METRIC_SCHEMA_VERSION,
                raw_json={"fixture": True},
            )
            for trade_date in trade_dates
        ],
        issues=[],
    )


def _app_config(indices: list[IndexConfig]) -> AppConfig:
    return AppConfig(indices=indices, rules=_rules())


def _index(
    code: str,
    *,
    market: str = "CN",
    provider: str = "akshare_csindex",
) -> IndexConfig:
    return IndexConfig(
        code=code,
        name=code,
        enabled=True,
        market=market,
        category="cn_broad",
        currency="CNY",
        timezone="Asia/Shanghai",
        primary_provider=provider,
        source_symbol=code,
    )


def _rules() -> RulesConfig:
    return RulesConfig(
        lookback_years=5,
        minimum_observations=500,
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
