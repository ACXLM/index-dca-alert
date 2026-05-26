from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, Sequence, TextIO
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from app.config import AppConfig, IndexConfig, PROJECT_ROOT, load_app_config
from app.jobs.backfill import run_backfill
from app.providers.base import HistoricalValuationProvider
from app.repositories.sqlite import (
    DcaRuleRepository,
    IndexRepository,
    MarketRunRepository,
    NotificationRepository,
    SignalInput,
    SignalRepository,
    UserIndexSubscriptionRepository,
    UserRepository,
    ValuationRepository,
    connect,
    initialize_database,
    utc_now_iso,
)
from app.services.notifications import (
    NotificationChannel,
    NotificationContext,
    NotificationDispatcher,
    NotificationError,
    NotificationResult,
    TelegramChannel,
    TelegramConfig,
)
from app.services.valuation_signals import SignalResult, ValuationSnapshot, calculate_signal


SUPPORTED_MARKETS = ("CN", "HK", "US")
MARKET_TIMEZONES = {
    "CN": "Asia/Shanghai",
    "HK": "Asia/Hong_Kong",
    "US": "America/New_York",
}
MARKET_READY_TIME = time(16, 30)
LOCAL_DISABLED_TARGET = "local-disabled"


@dataclass(frozen=True)
class DailyRunResult:
    market: str
    trade_date: str
    run_type: str
    status: str
    processed_indices: int = 0
    signals_written: int = 0
    notifications_sent: int = 0
    skipped_reason: str | None = None
    error_message: str | None = None


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_daily(
        db_path=args.db_path,
        market=args.market,
        trade_date=args.trade_date,
        run_type=args.run_type,
        force=args.force,
        dry_run=args.dry_run,
    )
    return 0 if result.status in {"success", "skipped"} else 1


def run_daily(
    *,
    db_path: str | Path,
    market: str | None = None,
    trade_date: str | None = None,
    run_type: str = "primary",
    force: bool = False,
    dry_run: bool = False,
    providers: dict[str, HistoricalValuationProvider] | None = None,
    app_config: AppConfig | None = None,
    notification_channels: list[NotificationChannel] | None = None,
    notification_managers: list[Any] | None = None,
    env: dict[str, str] | None = None,
    env_path: str | Path | None = None,
    now: datetime | None = None,
    stdout: TextIO | None = None,
) -> DailyRunResult:
    current_time = _as_utc(now or datetime.now(UTC))
    selected_market = market or _first_open_market(current_time)
    if selected_market is None:
        skipped_date = current_time.date().isoformat()
        _print(stdout, "skipped: no supported market window is open")
        return DailyRunResult(
            market="",
            trade_date=skipped_date,
            run_type=run_type,
            status="skipped",
            skipped_reason="no_market_window",
        )

    normalized_market = selected_market.upper()
    selected_trade_date = trade_date or market_trade_date(normalized_market, current_time)

    if not force and not is_market_window_open(normalized_market, current_time):
        _print(stdout, f"skipped: {normalized_market} market window is not open for {selected_trade_date}")
        return DailyRunResult(
            market=normalized_market,
            trade_date=selected_trade_date,
            run_type=run_type,
            status="skipped",
            skipped_reason="market_window_closed",
        )

    initialize_database(db_path)
    with connect(db_path) as conn:
        market_repo = MarketRunRepository(conn)
        if (
            not force
            and market_repo.has_successful_market_date(normalized_market, selected_trade_date)
        ):
            _print(stdout, f"skipped: {normalized_market} {selected_trade_date} already succeeded")
            return DailyRunResult(
                market=normalized_market,
                trade_date=selected_trade_date,
                run_type=run_type,
                status="skipped",
                skipped_reason="already_succeeded",
            )

    started_at = utc_now_iso()
    try:
        return _run_market(
            db_path=db_path,
            market=normalized_market,
            trade_date=selected_trade_date,
            run_type=run_type,
            started_at=started_at,
            providers=providers,
            app_config=app_config,
            notification_channels=notification_channels,
            notification_managers=notification_managers,
            env=env if env is not None else _load_runtime_env(env_path),
            dry_run=dry_run,
            stdout=stdout,
        )
    except Exception as exc:  # noqa: BLE001 - job boundary must persist failure context.
        error_message = _sanitize_runtime_error(str(exc))
        with connect(db_path) as conn:
            MarketRunRepository(conn).upsert_run(
                normalized_market,
                selected_trade_date,
                run_type,
                "failed",
                started_at=started_at,
                finished_at=utc_now_iso(),
                error_message=error_message,
            )
        _print(stdout, f"failed: {normalized_market} {selected_trade_date} {error_message}")
        return DailyRunResult(
            market=normalized_market,
            trade_date=selected_trade_date,
            run_type=run_type,
            status="failed",
            error_message=error_message,
        )


def is_market_window_open(market: str, now: datetime | None = None) -> bool:
    local_now = _market_local_time(market, now or datetime.now(UTC))
    return local_now.weekday() < 5 and local_now.time() >= MARKET_READY_TIME


def market_trade_date(market: str, now: datetime | None = None) -> str:
    return _market_local_time(market, now or datetime.now(UTC)).date().isoformat()


def _run_market(
    *,
    db_path: str | Path,
    market: str,
    trade_date: str,
    run_type: str,
    started_at: str,
    providers: dict[str, HistoricalValuationProvider] | None,
    app_config: AppConfig | None,
    notification_channels: list[NotificationChannel] | None,
    notification_managers: list[Any] | None,
    env: dict[str, str],
    dry_run: bool,
    stdout: TextIO | None,
) -> DailyRunResult:
    config = app_config or load_app_config()
    trade_day = date.fromisoformat(trade_date)

    run_backfill(
        db_path=db_path,
        years=config.rules.lookback_years,
        market=market,
        providers=providers,
        app_config=config,
        today=trade_day,
    )

    processed_indices = 0
    signals_written = 0
    notifications_sent = 0
    usable_indices = 0

    with connect(db_path) as conn:
        index_repo = IndexRepository(conn)
        DcaRuleRepository(conn).seed(config.rules)
        valuation_repo = ValuationRepository(conn)
        user_repo = UserRepository(conn)
        subscription_repo = UserIndexSubscriptionRepository(conn)
        signal_repo = SignalRepository(conn)
        notification_repo = NotificationRepository(conn)
        dispatcher = _notification_dispatcher(
            channels=notification_channels,
            managers=notification_managers,
            notification_repo=notification_repo,
            env=env,
            dry_run=dry_run,
        )

        default_user = user_repo.get_or_create("default")

        for index in _select_market_indices(config.indices, market):
            processed_indices += 1
            index_row = index_repo.get_by_code(index.code)
            if index_row is None:
                raise RuntimeError(f"seeded index not found: {index.code}")
            index_id = str(index_row["id"])
            current_row = valuation_repo.latest_for_index_on_or_before(index_id, trade_date)
            if current_row is None:
                continue

            history_rows = valuation_repo.history_for_index(
                index_id,
                _history_start_date(trade_day, config.rules.lookback_years),
                trade_date,
            )
            signal_result = calculate_signal(
                _snapshot_from_row(current_row),
                [_snapshot_from_row(row) for row in history_rows],
                index.category,
                config.rules,
                used_fallback=str(current_row["source_type"]) != "native_index",
            )
            usable_indices += 1

            subscription = subscription_repo.get_or_create(
                default_user["id"],
                index_id,
                config.rules.base_amount,
            )
            signal_id = signal_repo.upsert(
                _signal_input(
                    signal_result=signal_result,
                    subscription_id=str(subscription["id"]),
                    index_id=index_id,
                    base_amount=float(subscription["base_amount"]),
                )
            )
            signals_written += 1

            if dispatcher is not None:
                results = dispatcher.dispatch(
                    _notification_context(
                        signal_id=signal_id,
                        index=index,
                        current=_snapshot_from_row(current_row),
                        signal=signal_result,
                        base_amount=float(subscription["base_amount"]),
                    )
                )
                notifications_sent += sum(1 for result in results if result.status == "sent")

        market_repo = MarketRunRepository(conn)
        if usable_indices == 0:
            error = "no usable valuation data for selected indices"
            market_repo.upsert_run(
                market,
                trade_date,
                run_type,
                "failed",
                started_at=started_at,
                finished_at=utc_now_iso(),
                error_message=error,
            )
            _print(stdout, f"failed: {market} {trade_date} {error}")
            return DailyRunResult(
                market=market,
                trade_date=trade_date,
                run_type=run_type,
                status="failed",
                processed_indices=processed_indices,
                signals_written=signals_written,
                notifications_sent=notifications_sent,
                error_message=error,
            )

        market_repo.upsert_run(
            market,
            trade_date,
            run_type,
            "success",
            started_at=started_at,
            finished_at=utc_now_iso(),
        )

    _print(
        stdout,
        (
            f"success: {market} {trade_date} processed={processed_indices} "
            f"signals={signals_written} notifications_sent={notifications_sent}"
        ),
    )
    return DailyRunResult(
        market=market,
        trade_date=trade_date,
        run_type=run_type,
        status="success",
        processed_indices=processed_indices,
        signals_written=signals_written,
        notifications_sent=notifications_sent,
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the daily index DCA workflow.")
    parser.add_argument("--market", choices=SUPPORTED_MARKETS, default=None)
    parser.add_argument("--trade-date", default=None)
    parser.add_argument("--run-type", choices=["primary", "fallback", "manual"], default="primary")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db-path", default="data/index_dca.sqlite")
    return parser.parse_args(argv)


def _notification_dispatcher(
    *,
    channels: list[NotificationChannel] | None,
    managers: list[Any] | None,
    notification_repo: NotificationRepository,
    env: dict[str, str],
    dry_run: bool,
) -> NotificationDispatcher | None:
    if dry_run:
        return None
    if managers is not None:
        return NotificationDispatcher(managers, repository=notification_repo)
    if channels is not None:
        return NotificationDispatcher(
            [_ChannelAsManager(ch) for ch in channels],
            repository=notification_repo,
        )
    if not env.get("TG_BOT_TOKEN") or not env.get("TG_CHAT_ID"):
        return None
    try:
        return NotificationDispatcher(
            [TelegramChannel(TelegramConfig(bot_token=env["TG_BOT_TOKEN"], chat_id=env["TG_CHAT_ID"]))],
            repository=notification_repo,
        )
    except NotificationError:
        return None


class _ChannelAsManager:
    def __init__(self, channel: NotificationChannel) -> None:
        self._channel = channel
        self.channel_type = channel.name

    def dispatch_signal(
        self,
        context: NotificationContext,
        repository: NotificationRepository,
    ) -> list[NotificationResult]:
        result = self._channel.send(context)
        return [result]


def _load_runtime_env(env_path: str | Path | None) -> dict[str, str]:
    load_dotenv(dotenv_path=env_path or PROJECT_ROOT / ".env", override=False)
    return os.environ


def _signal_input(
    *,
    signal_result: SignalResult,
    subscription_id: str,
    index_id: str,
    base_amount: float,
) -> SignalInput:
    return SignalInput(
        user_index_subscription_id=subscription_id,
        index_id=index_id,
        trade_date=signal_result.trade_date,
        pe_percentile=signal_result.percentiles.pe,
        pb_percentile=signal_result.percentiles.pb,
        cape_percentile=signal_result.percentiles.cape,
        dividend_yield_percentile=signal_result.percentiles.dividend_yield,
        dividend_yield_inverse_percentile=signal_result.percentiles.dividend_yield_inverse,
        price_percentile=signal_result.percentiles.price,
        composite_percentile=signal_result.composite_percentile,
        signal_quality=signal_result.signal_quality,
        valuation_zone=signal_result.valuation_zone,
        dca_ratio=signal_result.dca_ratio,
        suggested_amount=round(base_amount * signal_result.dca_ratio, 2),
        message=signal_result.message,
    )


def _notification_context(
    *,
    signal_id: str,
    index: IndexConfig,
    current: ValuationSnapshot,
    signal: SignalResult,
    base_amount: float,
) -> NotificationContext:
    return NotificationContext(
        signal_id=signal_id,
        index_name=index.name,
        trade_date=signal.trade_date,
        market=index.market,
        category=index.category,
        pe=current.pe,
        pe_percentile=signal.percentiles.pe,
        pb=current.pb,
        pb_percentile=signal.percentiles.pb,
        cape_percentile=signal.percentiles.cape,
        dividend_yield_percentile=signal.percentiles.dividend_yield,
        price_percentile=signal.percentiles.price,
        composite_percentile=signal.composite_percentile,
        signal_quality=signal.signal_quality,
        valuation_zone=signal.valuation_zone,
        base_amount=base_amount,
        dca_ratio=signal.dca_ratio,
        suggested_amount=round(base_amount * signal.dca_ratio, 2),
    )


def _snapshot_from_row(row: object) -> ValuationSnapshot:
    return ValuationSnapshot(
        trade_date=str(row["trade_date"]),  # type: ignore[index]
        pe=_optional_float(row["pe"]),  # type: ignore[index]
        pb=_optional_float(row["pb"]),  # type: ignore[index]
        cape=_optional_float(row["cape"]),  # type: ignore[index]
        dividend_yield=_optional_float(row["dividend_yield"]),  # type: ignore[index]
        close=_optional_float(row["close"]),  # type: ignore[index]
        used_fallback=str(row["source_type"]) != "native_index",  # type: ignore[index]
    )


def _select_market_indices(indices: list[IndexConfig], market: str) -> list[IndexConfig]:
    return [index for index in indices if index.enabled and index.market == market]


def _first_open_market(now: datetime) -> str | None:
    for market in SUPPORTED_MARKETS:
        if is_market_window_open(market, now):
            return market
    return None


def _market_local_time(market: str, now: datetime) -> datetime:
    normalized = market.upper()
    if normalized not in MARKET_TIMEZONES:
        raise ValueError(f"unsupported market: {market}")
    return _as_utc(now).astimezone(ZoneInfo(MARKET_TIMEZONES[normalized]))


def _history_start_date(trade_day: date, years: int) -> str:
    try:
        return trade_day.replace(year=trade_day.year - years).isoformat()
    except ValueError:
        return trade_day.replace(month=2, day=28, year=trade_day.year - years).isoformat()


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _sanitize_runtime_error(message: str) -> str:
    token = os.environ.get("TG_BOT_TOKEN")
    if token:
        message = message.replace(token, "[redacted]")
    return message[:500]


def _print(stdout: TextIO | None, message: str) -> None:
    if stdout is None:
        print(message)
    else:
        print(message, file=stdout)


if __name__ == "__main__":
    raise SystemExit(main())
