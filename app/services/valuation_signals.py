from __future__ import annotations

from dataclasses import dataclass

from app.config import RulesConfig, ZoneRule


NON_ACTIONABLE_ZONE = "不可用"


@dataclass(frozen=True)
class ValuationSnapshot:
    trade_date: str
    pe: float | None = None
    pb: float | None = None
    cape: float | None = None
    dividend_yield: float | None = None
    close: float | None = None
    used_fallback: bool = False


@dataclass(frozen=True)
class MetricPercentiles:
    pe: float | None = None
    pb: float | None = None
    cape: float | None = None
    dividend_yield: float | None = None
    dividend_yield_inverse: float | None = None
    price: float | None = None

    def as_weighted_metrics(self) -> dict[str, float | None]:
        return {
            "pe": self.pe,
            "pb": self.pb,
            "cape": self.cape,
            "dividend_yield_inverse": self.dividend_yield_inverse,
            "price": self.price,
        }


@dataclass(frozen=True)
class SignalResult:
    trade_date: str
    percentiles: MetricPercentiles
    composite_percentile: float | None
    signal_quality: str
    valuation_zone: str
    dca_ratio: float
    suggested_amount: float
    message: str = ""


def percentile_rank(
    values: list[float | None],
    current: float | None,
    minimum_observations: int,
) -> float | None:
    clean = [value for value in values if value is not None and value > 0]
    if current is None or current <= 0 or len(clean) < minimum_observations:
        return None
    count = sum(1 for value in clean if value <= current)
    return round(count / len(clean) * 100, 2)


def calculate_metric_percentiles(
    current: ValuationSnapshot,
    history: list[ValuationSnapshot],
    minimum_observations: int,
) -> MetricPercentiles:
    dividend_yield = percentile_rank(
        [snapshot.dividend_yield for snapshot in history],
        current.dividend_yield,
        minimum_observations,
    )
    dividend_yield_inverse = None
    if dividend_yield is not None:
        dividend_yield_inverse = round(100 - dividend_yield, 2)

    return MetricPercentiles(
        pe=percentile_rank([snapshot.pe for snapshot in history], current.pe, minimum_observations),
        pb=percentile_rank([snapshot.pb for snapshot in history], current.pb, minimum_observations),
        cape=percentile_rank(
            [snapshot.cape for snapshot in history],
            current.cape,
            minimum_observations,
        ),
        dividend_yield=dividend_yield,
        dividend_yield_inverse=dividend_yield_inverse,
        price=percentile_rank(
            [snapshot.close for snapshot in history],
            current.close,
            minimum_observations,
        ),
    )


def composite_score(
    percentiles: MetricPercentiles | dict[str, float | None],
    weights: dict[str, float],
) -> float | None:
    values = percentiles.as_weighted_metrics() if isinstance(percentiles, MetricPercentiles) else percentiles
    score = 0.0
    weight_sum = 0.0
    for metric, weight in weights.items():
        value = values.get(metric)
        if value is None:
            continue
        score += value * weight
        weight_sum += weight
    if weight_sum == 0:
        return None
    return round(score / weight_sum, 2)


def select_zone(composite_percentile: float, zone_rules: list[ZoneRule]) -> ZoneRule:
    for index, zone_rule in enumerate(zone_rules):
        is_final_rule = index == len(zone_rules) - 1
        if zone_rule.min <= composite_percentile < zone_rule.max:
            return zone_rule
        if is_final_rule and composite_percentile == zone_rule.max:
            return zone_rule
    raise ValueError(f"composite percentile does not match any zone: {composite_percentile}")


def calculate_signal(
    current: ValuationSnapshot,
    history: list[ValuationSnapshot],
    category: str,
    rules: RulesConfig,
    *,
    used_fallback: bool = False,
) -> SignalResult:
    weights = rules.metric_weights[category]
    percentiles = calculate_metric_percentiles(
        current,
        history,
        rules.minimum_observations,
    )
    composite_percentile = composite_score(percentiles, weights)
    if composite_percentile is None:
        quality = _quality_without_composite(percentiles, weights)
        return _non_actionable_signal(current.trade_date, percentiles, quality)

    zone = select_zone(composite_percentile, rules.zone_rules)
    quality = _quality_with_composite(percentiles, weights, used_fallback or current.used_fallback)
    suggested_amount = rules.base_amount * zone.dca_ratio
    return SignalResult(
        trade_date=current.trade_date,
        percentiles=percentiles,
        composite_percentile=composite_percentile,
        signal_quality=quality,
        valuation_zone=zone.zone,
        dca_ratio=zone.dca_ratio,
        suggested_amount=suggested_amount,
    )


def fetch_failed_signal(
    trade_date: str,
    *,
    message: str = "fetch_failed",
) -> SignalResult:
    return SignalResult(
        trade_date=trade_date,
        percentiles=MetricPercentiles(),
        composite_percentile=None,
        signal_quality="fetch_failed",
        valuation_zone=NON_ACTIONABLE_ZONE,
        dca_ratio=0,
        suggested_amount=0,
        message=message,
    )


def _quality_with_composite(
    percentiles: MetricPercentiles,
    weights: dict[str, float],
    used_fallback: bool,
) -> str:
    values = percentiles.as_weighted_metrics()
    missing_metric = any(values.get(metric) is None for metric in weights)
    if missing_metric or used_fallback:
        return "partial"
    return "complete"


def _quality_without_composite(percentiles: MetricPercentiles, weights: dict[str, float]) -> str:
    values = percentiles.as_weighted_metrics()
    any_weighted_metric_available = any(values.get(metric) is not None for metric in weights)
    if any_weighted_metric_available:
        return "partial"
    return "insufficient_history"


def _non_actionable_signal(
    trade_date: str,
    percentiles: MetricPercentiles,
    signal_quality: str,
) -> SignalResult:
    return SignalResult(
        trade_date=trade_date,
        percentiles=percentiles,
        composite_percentile=None,
        signal_quality=signal_quality,
        valuation_zone=NON_ACTIONABLE_ZONE,
        dca_ratio=0,
        suggested_amount=0,
    )
