from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from app.config import AppConfig, IndexConfig, load_app_config
from app.providers.base import HistoricalValuationProvider, ProviderError, ProviderResult
from app.providers.registry import default_provider_registry
from app.repositories.sqlite import (
    DataQualityEventRepository,
    DcaRuleRepository,
    IndexRepository,
    ValuationRepository,
    connect,
    initialize_database,
)


@dataclass(frozen=True)
class BackfillResult:
    processed_indices: int
    inserted_or_updated_rows: int
    data_quality_events: int


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    run_backfill(
        db_path=args.db_path,
        years=args.years,
        market=args.market,
        index_code=args.index_code,
    )
    return 0


def run_backfill(
    *,
    db_path: str | Path,
    years: int | None = None,
    market: str | None = None,
    index_code: str | None = None,
    providers: dict[str, HistoricalValuationProvider] | None = None,
    app_config: AppConfig | None = None,
    today: date | None = None,
) -> BackfillResult:
    config = app_config or load_app_config()
    lookback_years = years or config.rules.lookback_years
    end = today or date.today()
    start = _subtract_years(end, lookback_years)
    start_date = start.isoformat()
    end_date = end.isoformat()

    initialize_database(db_path)
    provider_registry = providers or default_provider_registry()

    processed_indices = 0
    valuation_count = 0
    event_count = 0

    with connect(db_path) as conn:
        index_repo = IndexRepository(conn)
        dca_rule_repo = DcaRuleRepository(conn)
        valuation_repo = ValuationRepository(conn)
        event_repo = DataQualityEventRepository(conn)

        index_repo.seed(config.indices)
        dca_rule_repo.seed(config.rules)

        for index in _select_indices(config.indices, market=market, index_code=index_code):
            index_row = index_repo.get_by_code(index.code)
            if index_row is None:
                raise RuntimeError(f"seeded index not found: {index.code}")
            index_id = str(index_row["id"])
            provider = provider_registry.get(index.primary_provider)
            if provider is None:
                event_count += _record_event(
                    event_repo,
                    index_id,
                    source=index.primary_provider,
                    event_type="provider_failure",
                    message=f"no provider registered for {index.primary_provider}",
                )
                processed_indices += 1
                continue

            try:
                result = provider.fetch_history(index, start_date, end_date)
            except ProviderError as exc:
                event_count += _record_event(
                    event_repo,
                    index_id,
                    source=exc.provider,
                    event_type="provider_failure",
                    message=str(exc),
                )
                processed_indices += 1
                continue

            valuation_count += _persist_provider_result(
                index_id=index_id,
                index=index,
                result=result,
                start_date=start_date,
                valuation_repo=valuation_repo,
                event_repo=event_repo,
            )
            event_count += len(result.issues)
            if _has_coverage_gap(result, start_date):
                event_count += _record_event(
                    event_repo,
                    index_id,
                    source=_result_source(result, index.primary_provider),
                    event_type="coverage_gap",
                    message=f"provider history starts after requested start date {start_date}",
                    trade_date=start_date,
                )
            processed_indices += 1

    return BackfillResult(
        processed_indices=processed_indices,
        inserted_or_updated_rows=valuation_count,
        data_quality_events=event_count,
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill index valuation history.")
    parser.add_argument("--years", type=int, default=None)
    parser.add_argument("--market", choices=["CN", "HK", "US"], default=None)
    parser.add_argument("--index-code", default=None)
    parser.add_argument("--db-path", default="data/index_dca.sqlite")
    return parser.parse_args(argv)


def _select_indices(
    indices: list[IndexConfig],
    *,
    market: str | None,
    index_code: str | None,
) -> list[IndexConfig]:
    selected = [index for index in indices if index.enabled]
    if market is not None:
        selected = [index for index in selected if index.market == market]
    if index_code is not None:
        selected = [index for index in selected if index.code == index_code]
    return selected


def _persist_provider_result(
    *,
    index_id: str,
    index: IndexConfig,
    result: ProviderResult,
    start_date: str,
    valuation_repo: ValuationRepository,
    event_repo: DataQualityEventRepository,
) -> int:
    row_count = 0
    for issue in result.issues:
        _record_event(
            event_repo,
            index_id,
            source=_result_source(result, index.primary_provider),
            event_type=issue.event_type,
            message=issue.message,
            trade_date=issue.trade_date,
        )
    for valuation in result.valuations:
        valuation_repo.upsert(valuation.to_valuation_input(index_id))
        row_count += 1
    return row_count


def _record_event(
    event_repo: DataQualityEventRepository,
    index_id: str,
    *,
    source: str,
    event_type: str,
    message: str,
    trade_date: str | None = None,
) -> int:
    event_repo.create_event(
        index_id=index_id,
        source=source,
        event_type=event_type,
        message=message,
        trade_date=trade_date,
    )
    return 1


def _has_coverage_gap(result: ProviderResult, start_date: str) -> bool:
    if not result.valuations:
        return False
    earliest = min(valuation.trade_date for valuation in result.valuations)
    return earliest > start_date


def _result_source(result: ProviderResult, fallback_source: str) -> str:
    if result.valuations:
        return result.valuations[0].source
    return fallback_source


def _subtract_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year - years)


if __name__ == "__main__":
    raise SystemExit(main())
