from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.config import IndexConfig
from app.repositories.sqlite import ValuationInput


@dataclass(frozen=True)
class ProviderError(Exception):
    provider: str
    symbol: str
    message: str

    def __str__(self) -> str:
        return f"{self.provider} failed for {self.symbol}: {self.message}"


@dataclass(frozen=True)
class ProviderRowIssue:
    event_type: str
    message: str
    trade_date: str | None = None
    raw_json: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProviderValuation:
    trade_date: str
    source: str
    source_type: str
    metric_schema_version: str
    pe: float | None = None
    pb: float | None = None
    cape: float | None = None
    dividend_yield: float | None = None
    close: float | None = None
    raw_json: dict[str, Any] | None = None

    def to_valuation_input(self, index_id: str) -> ValuationInput:
        return ValuationInput(
            index_id=index_id,
            trade_date=self.trade_date,
            pe=self.pe,
            pb=self.pb,
            cape=self.cape,
            dividend_yield=self.dividend_yield,
            close=self.close,
            source=self.source,
            source_type=self.source_type,
            metric_schema_version=self.metric_schema_version,
            raw_json=self.raw_json,
        )


@dataclass(frozen=True)
class ProviderResult:
    valuations: list[ProviderValuation]
    issues: list[ProviderRowIssue]


class HistoricalValuationProvider(Protocol):
    def fetch_history(
        self,
        index: IndexConfig,
        start_date: str,
        end_date: str,
    ) -> ProviderResult:
        ...


def validate_provider_valuation(row: ProviderValuation) -> ProviderRowIssue | None:
    if not row.trade_date:
        return ProviderRowIssue(
            event_type="missing_required_field",
            message="provider row missing trade_date",
            raw_json=row.raw_json,
        )
    values = [row.pe, row.pb, row.cape, row.dividend_yield, row.close]
    if not any(value is not None and value > 0 for value in values):
        return ProviderRowIssue(
            event_type="invalid_row",
            message="provider row has no positive metric or close value",
            trade_date=row.trade_date,
            raw_json=row.raw_json,
        )
    return None
