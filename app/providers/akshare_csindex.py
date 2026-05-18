from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from app.config import IndexConfig
from app.providers.base import (
    ProviderError,
    ProviderResult,
    ProviderRowIssue,
    ProviderValuation,
    validate_provider_valuation,
)


SOURCE = "akshare_csindex"
SOURCE_TYPE = "native_index"
METRIC_SCHEMA_VERSION = "csindex_v1"


class AkshareCsindexProvider:
    def __init__(self, client: Any | None = None) -> None:
        self.client = client

    def fetch_history(
        self,
        index: IndexConfig,
        start_date: str,
        end_date: str,
    ) -> ProviderResult:
        rows = self._fetch_rows(index)
        return normalize_akshare_csindex_rows(rows, start_date=start_date, end_date=end_date)

    def _fetch_rows(self, index: IndexConfig) -> Iterable[dict[str, Any]]:
        try:
            client = self.client or _load_akshare()
            data = client.stock_zh_index_value_csindex(symbol=index.source_symbol)
        except Exception as exc:  # noqa: BLE001 - provider adapters wrap third-party failures.
            raise ProviderError(SOURCE, index.source_symbol, str(exc)) from exc
        return _iter_records(data)


def normalize_akshare_csindex_rows(
    rows: Iterable[dict[str, Any]],
    *,
    start_date: str,
    end_date: str,
) -> ProviderResult:
    valuations: list[ProviderValuation] = []
    issues: list[ProviderRowIssue] = []

    for raw_row in rows:
        try:
            valuation = _normalize_row(raw_row)
        except ProviderError as exc:
            issues.append(
                ProviderRowIssue(
                    event_type="normalization_error",
                    message=str(exc),
                    raw_json=_json_safe_raw_row(raw_row),
                )
            )
            continue

        issue = validate_provider_valuation(valuation)
        if issue is not None:
            issues.append(issue)
            continue
        if start_date <= valuation.trade_date <= end_date:
            valuations.append(valuation)

    if not valuations and not issues:
        issues.append(
            ProviderRowIssue(
                event_type="empty_response",
                message="provider returned no rows",
            )
        )

    return ProviderResult(valuations=valuations, issues=issues)


def _normalize_row(raw_row: dict[str, Any]) -> ProviderValuation:
    trade_date = _date_value(raw_row, ["日期", "date", "trade_date", "交易日期"])
    if trade_date is None:
        return ProviderValuation(
            trade_date="",
            source=SOURCE,
            source_type=SOURCE_TYPE,
            metric_schema_version=METRIC_SCHEMA_VERSION,
            raw_json=_json_safe_raw_row(raw_row),
        )

    return ProviderValuation(
        trade_date=trade_date,
        pe=_float_value(raw_row, ["市盈率", "pe", "PE", "pe_ttm", "市盈率1"]),
        pb=_float_value(raw_row, ["市净率", "pb", "PB"]),
        dividend_yield=_float_value(raw_row, ["股息率", "dividend_yield", "股息率1"]),
        close=_float_value(raw_row, ["收盘", "close", "收盘点位", "指数点位"]),
        source=SOURCE,
        source_type=SOURCE_TYPE,
        metric_schema_version=METRIC_SCHEMA_VERSION,
        raw_json=_json_safe_raw_row(raw_row),
    )


def _iter_records(data: Any) -> Iterable[dict[str, Any]]:
    if hasattr(data, "to_dict"):
        records = data.to_dict("records")
        return [dict(record) for record in records]
    return [dict(row) for row in data]


def _load_akshare() -> Any:
    try:
        import akshare as ak  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ProviderError(SOURCE, "akshare", "akshare is not installed") from exc
    return ak


def _date_value(raw_row: dict[str, Any], aliases: list[str]) -> str | None:
    value = _first_present(raw_row, aliases)
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if len(text) >= 10:
        return text[:10]
    raise ProviderError(SOURCE, "row", f"invalid trade date: {value}")


def _float_value(raw_row: dict[str, Any], aliases: list[str]) -> float | None:
    value = _first_present(raw_row, aliases)
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.strip().replace("%", "")
        if value in {"", "-", "--", "nan", "NaN", "None"}:
            return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ProviderError(SOURCE, "row", f"invalid numeric value: {value}") from None
    if parsed <= 0:
        return None
    return parsed


def _first_present(raw_row: dict[str, Any], aliases: list[str]) -> Any | None:
    for alias in aliases:
        if alias in raw_row:
            return raw_row[alias]
    return None


def _json_safe_raw_row(raw_row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe_value(value) for key, value in raw_row.items()}


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return _json_safe_value(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and value != value:
        return None
    return value
