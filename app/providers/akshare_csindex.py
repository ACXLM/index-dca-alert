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
LEGULEGU_SOURCE = "akshare_legulegu_index"
SOURCE_TYPE = "native_index"
METRIC_SCHEMA_VERSION = "csindex_v1"
LEGULEGU_METRIC_SCHEMA_VERSION = "legulegu_index_v1"
LEGULEGU_SYMBOLS = {
    "000300": "沪深300",
    "000905": "中证500",
}


class AkshareCsindexProvider:
    def __init__(self, client: Any | None = None) -> None:
        self.client = client

    def fetch_history(
        self,
        index: IndexConfig,
        start_date: str,
        end_date: str,
    ) -> ProviderResult:
        client = self.client or _load_akshare()
        if index.code in LEGULEGU_SYMBOLS:
            legulegu_result = self._fetch_legulegu_history(index, client, start_date, end_date)
            if _has_requested_coverage(legulegu_result, start_date):
                return legulegu_result
            raise _insufficient_history_error(index, legulegu_result, start_date)

        return normalize_akshare_csindex_rows(
            self._fetch_rows(index, client),
            start_date=start_date,
            end_date=end_date,
        )

    def _fetch_rows(self, index: IndexConfig, client: Any) -> Iterable[dict[str, Any]]:
        try:
            data = client.stock_zh_index_value_csindex(symbol=index.source_symbol)
        except Exception as exc:  # noqa: BLE001 - provider adapters wrap third-party failures.
            raise ProviderError(SOURCE, index.source_symbol, str(exc)) from exc
        return _iter_records(data)

    def _fetch_legulegu_history(
        self,
        index: IndexConfig,
        client: Any,
        start_date: str,
        end_date: str,
    ) -> ProviderResult:
        symbol = LEGULEGU_SYMBOLS[index.code]
        try:
            pe_rows = _iter_records(client.stock_index_pe_lg(symbol=symbol))
            pb_rows = _iter_records(client.stock_index_pb_lg(symbol=symbol))
        except Exception as exc:  # noqa: BLE001 - provider adapters wrap third-party failures.
            raise ProviderError(LEGULEGU_SOURCE, symbol, str(exc)) from exc
        return normalize_legulegu_index_rows(pe_rows, pb_rows, start_date=start_date, end_date=end_date)


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


def normalize_legulegu_index_rows(
    pe_rows: Iterable[dict[str, Any]],
    pb_rows: Iterable[dict[str, Any]],
    *,
    start_date: str,
    end_date: str,
) -> ProviderResult:
    pe_by_date = {_date: row for row in pe_rows if (_date := _date_value(row, ["日期", "date"])) is not None}
    pb_by_date = {_date: row for row in pb_rows if (_date := _date_value(row, ["日期", "date"])) is not None}
    trade_dates = sorted(set(pe_by_date) | set(pb_by_date))

    valuations: list[ProviderValuation] = []
    issues: list[ProviderRowIssue] = []
    for trade_date in trade_dates:
        if not start_date <= trade_date <= end_date:
            continue
        pe_row = pe_by_date.get(trade_date, {})
        pb_row = pb_by_date.get(trade_date, {})
        valuation = ProviderValuation(
            trade_date=trade_date,
            pe=_float_value(pe_row, ["滚动市盈率", "ttmPe", "市盈率", "pe"]),
            pb=_float_value(pb_row, ["市净率", "pb", "PB"]),
            close=_float_value(pe_row, ["指数", "close", "收盘"]),
            source=LEGULEGU_SOURCE,
            source_type=SOURCE_TYPE,
            metric_schema_version=LEGULEGU_METRIC_SCHEMA_VERSION,
            raw_json={
                "pe": _json_safe_raw_row(pe_row),
                "pb": _json_safe_raw_row(pb_row),
            },
        )
        issue = validate_provider_valuation(valuation)
        if issue is not None:
            issues.append(issue)
            continue
        valuations.append(valuation)

    if not valuations and not issues:
        issues.append(
            ProviderRowIssue(
                event_type="empty_response",
                message="legulegu provider returned no rows",
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


def _has_requested_coverage(result: ProviderResult, start_date: str) -> bool:
    if not result.valuations:
        return False
    return min(valuation.trade_date for valuation in result.valuations) <= start_date


def _insufficient_history_error(
    index: IndexConfig,
    result: ProviderResult,
    start_date: str,
) -> ProviderError:
    earliest = min((valuation.trade_date for valuation in result.valuations), default="none")
    return ProviderError(
        LEGULEGU_SOURCE,
        LEGULEGU_SYMBOLS[index.code],
        (
            "insufficient valuation history coverage: "
            f"earliest={earliest}, required_start<={start_date}"
        ),
    )


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
