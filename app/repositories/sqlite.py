from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import IndexConfig, PROJECT_ROOT, RulesConfig


DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "index_dca.sqlite"
SCHEMA_PATH = PROJECT_ROOT / "app" / "schema.sql"


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database(
    db_path: str | Path = DEFAULT_DB_PATH,
    schema_path: str | Path = SCHEMA_PATH,
) -> None:
    schema = Path(schema_path).read_text(encoding="utf-8")
    with connect(db_path) as conn:
        conn.executescript(schema)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ValuationInput:
    index_id: str
    trade_date: str
    source: str
    pe: float | None = None
    pb: float | None = None
    cape: float | None = None
    dividend_yield: float | None = None
    close: float | None = None
    source_type: str = "native_index"
    metric_schema_version: str = "v1"
    raw_json: str | dict[str, Any] | None = None


@dataclass(frozen=True)
class SignalInput:
    user_index_subscription_id: str
    index_id: str
    trade_date: str
    signal_quality: str
    valuation_zone: str
    dca_ratio: float
    suggested_amount: float
    message: str
    pe_percentile: float | None = None
    pb_percentile: float | None = None
    cape_percentile: float | None = None
    dividend_yield_percentile: float | None = None
    dividend_yield_inverse_percentile: float | None = None
    price_percentile: float | None = None
    composite_percentile: float | None = None


@dataclass(frozen=True)
class UserSubscriptionInput:
    user_id: str
    index_id: str
    notify_target: str
    base_amount: float = 1000
    notify_channel: str = "telegram"
    enabled: bool = True


@dataclass(frozen=True)
class ValuationCoverage:
    count: int
    first_date: str | None
    last_date: str | None


class IndexRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def seed(self, indices: list[IndexConfig]) -> None:
        now = utc_now_iso()
        with self.conn:
            for index in indices:
                self.conn.execute(
                    """
                    INSERT INTO indices (
                      id, code, name, market, category, currency, timezone,
                      primary_provider, source_symbol, enabled, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                      name = excluded.name,
                      market = excluded.market,
                      category = excluded.category,
                      currency = excluded.currency,
                      timezone = excluded.timezone,
                      primary_provider = excluded.primary_provider,
                      source_symbol = excluded.source_symbol,
                      enabled = excluded.enabled,
                      updated_at = excluded.updated_at
                    """,
                    (
                        str(uuid.uuid4()),
                        index.code,
                        index.name,
                        index.market,
                        index.category,
                        index.currency,
                        index.timezone,
                        index.primary_provider,
                        index.source_symbol,
                        int(index.enabled),
                        now,
                        now,
                    ),
                )

    def get_by_code(self, code: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM indices WHERE code = ?",
            (code,),
        ).fetchone()

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS count FROM indices").fetchone()
        return int(row["count"])


class DcaRuleRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def seed(self, rules: RulesConfig) -> None:
        now = utc_now_iso()
        zone_rules_json = json.dumps(
            [asdict(rule) for rule in rules.zone_rules],
            ensure_ascii=False,
            sort_keys=True,
        )
        with self.conn:
            for category, metric_weights in rules.metric_weights.items():
                self.conn.execute(
                    """
                    INSERT INTO dca_rules (
                      id, category, lookback_years, minimum_observations,
                      metric_weights_json, zone_rules_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(category) DO UPDATE SET
                      lookback_years = excluded.lookback_years,
                      minimum_observations = excluded.minimum_observations,
                      metric_weights_json = excluded.metric_weights_json,
                      zone_rules_json = excluded.zone_rules_json,
                      updated_at = excluded.updated_at
                    """,
                    (
                        str(uuid.uuid4()),
                        category,
                        rules.lookback_years,
                        rules.minimum_observations,
                        json.dumps(metric_weights, ensure_ascii=False, sort_keys=True),
                        zone_rules_json,
                        now,
                        now,
                    ),
                )

    def get_by_category(self, category: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM dca_rules WHERE category = ?",
            (category,),
        ).fetchone()

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS count FROM dca_rules").fetchone()
        return int(row["count"])


class ValuationRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert(self, valuation: ValuationInput) -> str:
        now = utc_now_iso()
        raw_json = _normalize_raw_json(valuation.raw_json)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO index_valuations (
                  id, index_id, trade_date, pe, pb, cape, dividend_yield, close,
                  source, source_type, metric_schema_version, raw_json,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(index_id, trade_date, source) DO UPDATE SET
                  pe = excluded.pe,
                  pb = excluded.pb,
                  cape = excluded.cape,
                  dividend_yield = excluded.dividend_yield,
                  close = excluded.close,
                  source_type = excluded.source_type,
                  metric_schema_version = excluded.metric_schema_version,
                  raw_json = excluded.raw_json,
                  updated_at = excluded.updated_at
                """,
                (
                    str(uuid.uuid4()),
                    valuation.index_id,
                    valuation.trade_date,
                    valuation.pe,
                    valuation.pb,
                    valuation.cape,
                    valuation.dividend_yield,
                    valuation.close,
                    valuation.source,
                    valuation.source_type,
                    valuation.metric_schema_version,
                    raw_json,
                    now,
                    now,
                ),
            )
        row = self.get_by_identity(valuation.index_id, valuation.trade_date, valuation.source)
        if row is None:
            raise RuntimeError("valuation upsert completed but row was not found")
        return str(row["id"])

    def get_by_identity(self, index_id: str, trade_date: str, source: str) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT * FROM index_valuations
            WHERE index_id = ? AND trade_date = ? AND source = ?
            """,
            (index_id, trade_date, source),
        ).fetchone()

    def history_for_index(
        self,
        index_id: str,
        start_date: str,
        end_date: str,
    ) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT * FROM index_valuations
                WHERE index_id = ? AND trade_date >= ? AND trade_date <= ?
                ORDER BY trade_date ASC
                """,
                (index_id, start_date, end_date),
            )
        )

    def latest_for_index_on_or_before(self, index_id: str, trade_date: str) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT * FROM index_valuations
            WHERE index_id = ? AND trade_date <= ?
            ORDER BY trade_date DESC, updated_at DESC
            LIMIT 1
            """,
            (index_id, trade_date),
        ).fetchone()

    def has_coverage(self, index_id: str, start_date: str, end_date: str) -> bool:
        coverage = self.coverage_for_index(index_id)
        if coverage.count == 0 or coverage.first_date is None or coverage.last_date is None:
            return False
        return coverage.first_date <= start_date and coverage.last_date >= end_date

    def coverage_for_index(self, index_id: str) -> ValuationCoverage:
        row = self.conn.execute(
            """
            SELECT
              COUNT(*) AS count,
              MIN(trade_date) AS first_date,
              MAX(trade_date) AS last_date
            FROM index_valuations
            WHERE index_id = ?
            """,
            (index_id,),
        ).fetchone()
        if row is None:
            return ValuationCoverage(count=0, first_date=None, last_date=None)
        return ValuationCoverage(
            count=int(row["count"]),
            first_date=str(row["first_date"]) if row["first_date"] is not None else None,
            last_date=str(row["last_date"]) if row["last_date"] is not None else None,
        )


class MarketRunRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert_run(
        self,
        market: str,
        trade_date: str,
        run_type: str,
        status: str,
        *,
        started_at: str | None = None,
        finished_at: str | None = None,
        error_message: str | None = None,
    ) -> str:
        started = started_at or utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO market_runs (
                  id, market, trade_date, run_type, status,
                  started_at, finished_at, error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(market, trade_date, run_type) DO UPDATE SET
                  status = excluded.status,
                  finished_at = excluded.finished_at,
                  error_message = excluded.error_message
                """,
                (
                    str(uuid.uuid4()),
                    market,
                    trade_date,
                    run_type,
                    status,
                    started,
                    finished_at,
                    error_message,
                ),
            )
        row = self.get_run(market, trade_date, run_type)
        if row is None:
            raise RuntimeError("market run upsert completed but row was not found")
        return str(row["id"])

    def get_run(self, market: str, trade_date: str, run_type: str) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT * FROM market_runs
            WHERE market = ? AND trade_date = ? AND run_type = ?
            """,
            (market, trade_date, run_type),
        ).fetchone()

    def has_successful_run(self, market: str, trade_date: str, run_type: str) -> bool:
        row = self.conn.execute(
            """
            SELECT 1 FROM market_runs
            WHERE market = ? AND trade_date = ? AND run_type = ? AND status = 'success'
            LIMIT 1
            """,
            (market, trade_date, run_type),
        ).fetchone()
        return row is not None

    def has_successful_market_date(self, market: str, trade_date: str) -> bool:
        row = self.conn.execute(
            """
            SELECT 1 FROM market_runs
            WHERE market = ? AND trade_date = ? AND status = 'success'
            LIMIT 1
            """,
            (market, trade_date),
        ).fetchone()
        return row is not None



class UserRepository:
    def __init__(self, conn):
        self.conn = conn

    def get_or_create(self, name: str):
        now = utc_now_iso()
        with self.conn:
            # Check first to avoid overwriting updated_at or creating conflict
            row = self.get_by_name(name)
            if row:
                return row
            user_id = str(uuid.uuid4())
            self.conn.execute(
                "INSERT INTO users (id, name, enabled, created_at, updated_at) VALUES (?, ?, 1, ?, ?)",
                (user_id, name, now, now)
            )
            return self.get_by_id(user_id)

    def get_by_name(self, name: str):
        return self.conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()

    def get_by_id(self, user_id: str):
        return self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


class UserIndexSubscriptionRepository:
    def __init__(self, conn):
        self.conn = conn

    def get_or_create(self, user_id: str, index_id: str, base_amount: float):
        now = utc_now_iso()
        with self.conn:
            row = self.get_by_identity(user_id, index_id)
            if row:
                return row
            sub_id = str(uuid.uuid4())
            self.conn.execute(
                "INSERT INTO user_index_subscriptions (id, user_id, index_id, base_amount, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
                (sub_id, user_id, index_id, base_amount, now, now)
            )
            return self.get_by_identity(user_id, index_id)

    def get_by_identity(self, user_id: str, index_id: str):
        return self.conn.execute("SELECT * FROM user_index_subscriptions WHERE user_id = ? AND index_id = ?", (user_id, index_id)).fetchone()

    def list_enabled_for_index(self, index_id: str):
        return list(self.conn.execute("SELECT * FROM user_index_subscriptions WHERE index_id = ? AND enabled = 1", (index_id,)))


class UserNotificationEndpointRepository:
    def __init__(self, conn):
        self.conn = conn

    def create(self, user_id: str, channel_type: str, target: str, credential_enc: str) -> str:
        now = utc_now_iso()
        endpoint_id = str(uuid.uuid4())
        with self.conn:
            self.conn.execute(
                "INSERT INTO user_notification_endpoints (id, user_id, channel_type, target, credential_enc, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (endpoint_id, user_id, channel_type, target, credential_enc, now, now)
            )
        return endpoint_id

    def get_by_identity(self, user_id: str, channel_type: str, target: str):
        return self.conn.execute("SELECT * FROM user_notification_endpoints WHERE user_id = ? AND channel_type = ? AND target = ?", (user_id, channel_type, target)).fetchone()

    def list_enabled_for_index_and_channel(self, index_id: str, channel_type: str):
        query = '''
        SELECT e.*
        FROM user_notification_endpoints e
        JOIN users u ON u.id = e.user_id
        JOIN user_index_subscriptions s ON s.user_id = e.user_id
        WHERE s.index_id = ?
          AND s.enabled = 1
          AND e.channel_type = ?
          AND e.enabled = 1
          AND u.enabled = 1
        '''
        return list(self.conn.execute(query, (index_id, channel_type)))

class UserSubscriptionRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, subscription: UserSubscriptionInput) -> str:
        now = utc_now_iso()
        subscription_id = str(uuid.uuid4())
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO user_subscriptions (
                  id, user_id, index_id, base_amount, notify_channel,
                  notify_target, enabled, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subscription_id,
                    subscription.user_id,
                    subscription.index_id,
                    subscription.base_amount,
                    subscription.notify_channel,
                    subscription.notify_target,
                    int(subscription.enabled),
                    now,
                    now,
                ),
            )
        return subscription_id

    def list_enabled_for_index(self, index_id: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT * FROM user_subscriptions
                WHERE index_id = ? AND enabled = 1
                ORDER BY created_at ASC
                """,
                (index_id,),
            )
        )

    def get_by_identity(
        self,
        *,
        user_id: str,
        index_id: str,
        notify_channel: str,
        notify_target: str,
    ) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT * FROM user_subscriptions
            WHERE user_id = ?
              AND index_id = ?
              AND notify_channel = ?
              AND notify_target = ?
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (user_id, index_id, notify_channel, notify_target),
        ).fetchone()

    def get_or_create_default(
        self,
        *,
        index_id: str,
        notify_target: str,
        base_amount: float,
        user_id: str = "default",
        notify_channel: str = "telegram",
    ) -> sqlite3.Row:
        row = self.get_by_identity(
            user_id=user_id,
            index_id=index_id,
            notify_channel=notify_channel,
            notify_target=notify_target,
        )
        if row is None:
            self.create(
                UserSubscriptionInput(
                    user_id=user_id,
                    index_id=index_id,
                    base_amount=base_amount,
                    notify_channel=notify_channel,
                    notify_target=notify_target,
                )
            )
            row = self.get_by_identity(
                user_id=user_id,
                index_id=index_id,
                notify_channel=notify_channel,
                notify_target=notify_target,
            )
        if row is None:
            raise RuntimeError("subscription create completed but row was not found")
        return row


class SignalRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert(self, signal: SignalInput) -> str:
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO valuation_signals (
                  id, user_index_subscription_id, index_id, trade_date,
                  pe_percentile, pb_percentile, cape_percentile,
                  dividend_yield_percentile, dividend_yield_inverse_percentile,
                  price_percentile, composite_percentile, signal_quality,
                  valuation_zone, dca_ratio, suggested_amount, message, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_index_subscription_id, trade_date) DO UPDATE SET
                  index_id = excluded.index_id,
                  pe_percentile = excluded.pe_percentile,
                  pb_percentile = excluded.pb_percentile,
                  cape_percentile = excluded.cape_percentile,
                  dividend_yield_percentile = excluded.dividend_yield_percentile,
                  dividend_yield_inverse_percentile = excluded.dividend_yield_inverse_percentile,
                  price_percentile = excluded.price_percentile,
                  composite_percentile = excluded.composite_percentile,
                  signal_quality = excluded.signal_quality,
                  valuation_zone = excluded.valuation_zone,
                  dca_ratio = excluded.dca_ratio,
                  suggested_amount = excluded.suggested_amount,
                  message = excluded.message
                """,
                (
                    str(uuid.uuid4()),
                    signal.user_index_subscription_id,
                    signal.index_id,
                    signal.trade_date,
                    signal.pe_percentile,
                    signal.pb_percentile,
                    signal.cape_percentile,
                    signal.dividend_yield_percentile,
                    signal.dividend_yield_inverse_percentile,
                    signal.price_percentile,
                    signal.composite_percentile,
                    signal.signal_quality,
                    signal.valuation_zone,
                    signal.dca_ratio,
                    signal.suggested_amount,
                    signal.message,
                    now,
                ),
            )
        row = self.get_by_identity(signal.user_index_subscription_id, signal.trade_date)
        if row is None:
            raise RuntimeError("signal upsert completed but row was not found")
        return str(row["id"])

    def get_by_identity(self, user_index_subscription_id: str, trade_date: str) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT * FROM valuation_signals
            WHERE user_index_subscription_id = ? AND trade_date = ?
            """,
            (user_index_subscription_id, trade_date),
        ).fetchone()


class NotificationRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create_attempt(
        self,
        signal_id: str,
        channel: str,
        target: str,
        status: str,
        *,
        endpoint_id: str,
        error_message: str | None = None,
        sent_at: str | None = None,
    ) -> str:
        now = utc_now_iso()
        notification_id = str(uuid.uuid4())
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO notifications (
                  id, signal_id, endpoint_id, channel, target, status,
                  error_message, sent_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    notification_id,
                    signal_id,
                    endpoint_id,
                    channel,
                    target,
                    status,
                    error_message,
                    sent_at,
                    now,
                ),
            )
        return notification_id

    def already_sent(self, signal_id: str, endpoint_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM notifications WHERE signal_id = ? AND endpoint_id = ? AND status = 'sent' LIMIT 1",
            (signal_id, endpoint_id)
        ).fetchone()
        return row is not None


class DataQualityEventRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create_event(
        self,
        index_id: str,
        source: str,
        event_type: str,
        message: str,
        *,
        trade_date: str | None = None,
    ) -> str:
        now = utc_now_iso()
        event_id = str(uuid.uuid4())
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO data_quality_events (
                  id, index_id, trade_date, source, event_type, message, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, index_id, trade_date, source, event_type, message, now),
            )
        return event_id


def _normalize_raw_json(raw_json: str | dict[str, Any] | None) -> str | None:
    if raw_json is None:
        return None
    if isinstance(raw_json, str):
        return raw_json
    return json.dumps(raw_json, ensure_ascii=False, sort_keys=True, default=str)
