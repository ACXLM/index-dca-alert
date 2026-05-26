from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from app.config import IndexConfig, RulesConfig, ZoneRule, load_app_config
from app.repositories.sqlite import (
    DcaRuleRepository,
    IndexRepository,
    MarketRunRepository,
    SignalInput,
    SignalRepository,
    UserIndexSubscriptionRepository,
    UserRepository,
    ValuationInput,
    ValuationRepository,
    connect,
    initialize_database,
)


def test_sqlite_initializes_from_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"

    initialize_database(db_path)

    with connect(db_path) as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {
        "indices",
        "index_valuations",
        "dca_rules",
        "users",
        "user_index_subscriptions",
        "user_notification_endpoints",
        "valuation_signals",
        "notifications",
        "market_runs",
        "data_quality_events",
    }.issubset(tables)


def test_foreign_keys_are_enabled_for_application_connections(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    initialize_database(db_path)

    with connect(db_path) as conn:
        row = conn.execute("PRAGMA foreign_keys").fetchone()

    assert row[0] == 1


def test_foreign_key_violation_fails(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    initialize_database(db_path)

    with connect(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            ValuationRepository(conn).upsert(
                ValuationInput(
                    index_id="missing-index-id",
                    trade_date="2026-05-17",
                    source="unit_test",
                    pe=10.0,
                )
            )


def test_seeds_configured_indices_idempotently_and_preserves_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    initialize_database(db_path)
    config = load_app_config()

    with connect(db_path) as conn:
        repo = IndexRepository(conn)
        repo.seed(config.indices)
        first_row = repo.get_by_code("000300")
        assert first_row is not None
        first_id = first_row["id"]

        changed_indices = [
            replace(index, name="沪深300 Updated") if index.code == "000300" else index
            for index in config.indices
        ]
        repo.seed(changed_indices)
        second_row = repo.get_by_code("000300")

        assert repo.count() == 6
        assert second_row is not None
        assert second_row["id"] == first_id
        assert second_row["name"] == "沪深300 Updated"


def test_seeds_dca_rules_idempotently_and_preserves_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    initialize_database(db_path)
    rules = _rules_config()

    with connect(db_path) as conn:
        repo = DcaRuleRepository(conn)
        repo.seed(rules)
        first_row = repo.get_by_category("cn_broad")
        assert first_row is not None
        first_id = first_row["id"]

        changed_rules = replace(rules, minimum_observations=600)
        repo.seed(changed_rules)
        second_row = repo.get_by_category("cn_broad")

        assert repo.count() == 1
        assert second_row is not None
        assert second_row["id"] == first_id
        assert second_row["minimum_observations"] == 600


def test_valuation_upsert_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    index_id = _seed_one_index(db_path)

    with connect(db_path) as conn:
        repo = ValuationRepository(conn)
        first_id = repo.upsert(
            ValuationInput(
                index_id=index_id,
                trade_date="2026-05-17",
                source="akshare_csindex",
                pe=11.0,
                raw_json={"pe": 11.0},
            )
        )
        second_id = repo.upsert(
            ValuationInput(
                index_id=index_id,
                trade_date="2026-05-17",
                source="akshare_csindex",
                pe=12.0,
                raw_json={"pe": 12.0},
            )
        )
        row = repo.get_by_identity(index_id, "2026-05-17", "akshare_csindex")

        assert second_id == first_id
        assert row is not None
        assert row["pe"] == 12.0


def test_valuation_coverage_requires_start_and_end_dates(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    index_id = _seed_one_index(db_path)

    with connect(db_path) as conn:
        repo = ValuationRepository(conn)
        for trade_date in ["2021-05-17", "2026-05-17"]:
            repo.upsert(
                ValuationInput(
                    index_id=index_id,
                    trade_date=trade_date,
                    source="akshare_legulegu_index",
                    pe=10.0,
                )
            )

        assert repo.has_coverage(index_id, "2021-05-17", "2026-05-17") is True
        assert repo.has_coverage(index_id, "2021-05-16", "2026-05-17") is False
        assert repo.has_coverage(index_id, "2021-05-17", "2026-05-18") is False


def test_signal_upsert_writes_one_signal_per_subscription_and_trade_date(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    index_id = _seed_one_index(db_path)

    with connect(db_path) as conn:
        user = UserRepository(conn).get_or_create("local")
        subscription = UserIndexSubscriptionRepository(conn).get_or_create(
            user["id"], index_id, 1000.0
        )
        subscription_id = str(subscription["id"])
        repo = SignalRepository(conn)
        first_id = repo.upsert(
            _signal_input(subscription_id, index_id, "2026-05-17", suggested_amount=1000)
        )
        second_id = repo.upsert(
            _signal_input(subscription_id, index_id, "2026-05-17", suggested_amount=1200)
        )
        row = repo.get_by_identity(subscription_id, "2026-05-17")

        assert second_id == first_id
        assert row is not None
        assert row["suggested_amount"] == 1200


def test_market_run_tracking_prevents_exact_duplicate_success(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    initialize_database(db_path)

    with connect(db_path) as conn:
        repo = MarketRunRepository(conn)
        first_id = repo.upsert_run("CN", "2026-05-17", "primary", "success")
        second_id = repo.upsert_run("CN", "2026-05-17", "primary", "success")

        assert second_id == first_id
        assert repo.has_successful_run("CN", "2026-05-17", "primary") is True


def test_market_run_successful_market_date_crosses_run_types(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    initialize_database(db_path)

    with connect(db_path) as conn:
        repo = MarketRunRepository(conn)
        repo.upsert_run("US", "2026-05-17", "primary", "success")

        assert repo.has_successful_run("US", "2026-05-17", "fallback") is False
        assert repo.has_successful_market_date("US", "2026-05-17") is True


def test_repository_write_rolls_back_on_failure(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    initialize_database(db_path)
    valid_index = _index_config()
    invalid_index = replace(valid_index, code="BROKEN", name=None)  # type: ignore[arg-type]

    with connect(db_path) as conn:
        repo = IndexRepository(conn)
        with pytest.raises(sqlite3.IntegrityError):
            repo.seed([valid_index, invalid_index])

        assert repo.count() == 0


def test_repository_values_are_parameterized(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    injection_text = "unit_test'); DROP TABLE indices; --"
    index_id = _seed_one_index(db_path)

    with connect(db_path) as conn:
        repo = ValuationRepository(conn)
        repo.upsert(
            ValuationInput(
                index_id=index_id,
                trade_date="2026-05-17",
                source=injection_text,
                pe=10.0,
            )
        )
        row = repo.get_by_identity(index_id, "2026-05-17", injection_text)
        index_count = conn.execute("SELECT COUNT(*) AS count FROM indices").fetchone()["count"]

        assert row is not None
        assert row["source"] == injection_text
        assert index_count == 1


def test_application_tables_use_text_primary_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    initialize_database(db_path)

    with connect(db_path) as conn:
        for table_name in _application_tables():
            columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            id_column = next(column for column in columns if column["name"] == "id")
            assert id_column["type"] == "TEXT"
            assert id_column["pk"] == 1


def test_natural_uniqueness_constraints_exist(tmp_path: Path) -> None:
    db_path = tmp_path / "index_dca.sqlite"
    initialize_database(db_path)

    with connect(db_path) as conn:
        assert _has_unique_index(conn, "index_valuations", ["index_id", "trade_date", "source"])
        assert _has_unique_index(conn, "valuation_signals", ["user_index_subscription_id", "trade_date"])
        assert _has_unique_index(conn, "market_runs", ["market", "trade_date", "run_type"])
        assert _has_unique_index(conn, "user_index_subscriptions", ["user_id", "index_id"])
        assert _has_unique_index(conn, "user_notification_endpoints", ["user_id", "channel_type", "target"])


def _seed_one_index(db_path: Path) -> str:
    initialize_database(db_path)
    with connect(db_path) as conn:
        repo = IndexRepository(conn)
        repo.seed([_index_config()])
        row = repo.get_by_code("000300")
        assert row is not None
        return str(row["id"])


def _index_config() -> IndexConfig:
    return IndexConfig(
        code="000300",
        name="CSI 300",
        market="CN",
        category="cn_broad",
        currency="CNY",
        timezone="Asia/Shanghai",
        primary_provider="akshare_csindex",
        source_symbol="000300",
        enabled=True,
    )


def _rules_config() -> RulesConfig:
    return RulesConfig(
        lookback_years=5,
        minimum_observations=500,
        base_amount=1000,
        metric_weights={
            "cn_broad": {
                "pe": 0.6,
                "pb": 0.4,
            }
        },
        zone_rules=[
            ZoneRule(min=0, max=15, zone="clearly_undervalued", dca_ratio=2.0),
            ZoneRule(min=15, max=30, zone="mildly_undervalued", dca_ratio=1.2),
            ZoneRule(min=30, max=60, zone="fair", dca_ratio=1.0),
            ZoneRule(min=60, max=80, zone="mildly_overvalued", dca_ratio=0.5),
            ZoneRule(min=80, max=100, zone="overvalued", dca_ratio=0.0),
        ],
    )


def _signal_input(
    subscription_id: str,
    index_id: str,
    trade_date: str,
    *,
    suggested_amount: float,
) -> SignalInput:
    return SignalInput(
        user_index_subscription_id=subscription_id,
        index_id=index_id,
        trade_date=trade_date,
        signal_quality="complete",
        valuation_zone="fair",
        dca_ratio=1.0,
        suggested_amount=suggested_amount,
        message="test signal",
        composite_percentile=45.0,
    )


def _application_tables() -> list[str]:
    return [
        "indices",
        "index_valuations",
        "dca_rules",
        "users",
        "user_index_subscriptions",
        "user_notification_endpoints",
        "valuation_signals",
        "notifications",
        "market_runs",
        "data_quality_events",
    ]


def _has_unique_index(
    conn: sqlite3.Connection,
    table_name: str,
    expected_columns: list[str],
) -> bool:
    indexes = conn.execute(f"PRAGMA index_list({table_name})").fetchall()
    for index in indexes:
        if not index["unique"]:
            continue
        columns = [
            row["name"]
            for row in conn.execute(f"PRAGMA index_info({index['name']})").fetchall()
        ]
        if columns == expected_columns:
            return True
    return False
