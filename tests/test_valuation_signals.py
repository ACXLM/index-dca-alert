from __future__ import annotations

import pytest

from app.config import RulesConfig, ZoneRule, load_app_config
from app.services.valuation_signals import (
    NON_ACTIONABLE_ZONE,
    MetricPercentiles,
    ValuationSnapshot,
    calculate_metric_percentiles,
    calculate_signal,
    composite_score,
    fetch_failed_signal,
    percentile_rank,
    select_zone,
)


def test_percentile_ignores_null_zero_and_negative_values() -> None:
    assert percentile_rank([None, -2, 0, 10, 20], 10, minimum_observations=2) == 50.0


def test_percentile_returns_none_below_observation_threshold() -> None:
    assert percentile_rank([10, 20], 10, minimum_observations=3) is None


def test_percentile_includes_current_trade_date_when_present() -> None:
    assert percentile_rank([10, 20, 30], 20, minimum_observations=3) == 66.67


def test_percentile_returns_deterministic_rounded_values() -> None:
    assert percentile_rank([10, 20, 30], 10, minimum_observations=3) == 33.33


def test_dividend_yield_percentile_is_reversed() -> None:
    percentiles = calculate_metric_percentiles(
        current=ValuationSnapshot(trade_date="2026-05-17", dividend_yield=3),
        history=[
            ValuationSnapshot(trade_date="2026-05-15", dividend_yield=1),
            ValuationSnapshot(trade_date="2026-05-16", dividend_yield=2),
            ValuationSnapshot(trade_date="2026-05-17", dividend_yield=3),
            ValuationSnapshot(trade_date="2026-05-18", dividend_yield=4),
        ],
        minimum_observations=4,
    )

    assert percentiles.dividend_yield == 75.0
    assert percentiles.dividend_yield_inverse == 25.0


def test_price_metric_uses_close_value() -> None:
    percentiles = calculate_metric_percentiles(
        current=ValuationSnapshot(trade_date="2026-05-17", close=200),
        history=[
            ValuationSnapshot(trade_date="2026-05-15", close=100),
            ValuationSnapshot(trade_date="2026-05-16", close=200),
            ValuationSnapshot(trade_date="2026-05-17", close=300),
        ],
        minimum_observations=3,
    )

    assert percentiles.price == 66.67


def test_composite_score_renormalizes_missing_metrics() -> None:
    score = composite_score(
        MetricPercentiles(pe=20, pb=None),
        {
            "pe": 0.6,
            "pb": 0.4,
        },
    )

    assert score == 20


def test_composite_score_returns_none_when_all_weighted_metrics_are_missing() -> None:
    score = composite_score(
        MetricPercentiles(pe=None, pb=None),
        {
            "pe": 0.6,
            "pb": 0.4,
        },
    )

    assert score is None


@pytest.mark.parametrize(
    ("score", "expected_zone", "expected_ratio"),
    [
        (0, "明显低估", 2.0),
        (15, "合理偏低", 1.2),
        (30, "合理", 1.0),
        (60, "合理偏高", 0.5),
        (80, "高估", 0.0),
        (100, "高估", 0.0),
    ],
)
def test_zone_boundaries_are_deterministic(
    score: float,
    expected_zone: str,
    expected_ratio: float,
) -> None:
    zone = select_zone(score, _rules().zone_rules)

    assert zone.zone == expected_zone
    assert zone.dca_ratio == expected_ratio


def test_suggested_amount_uses_base_amount_times_dca_ratio() -> None:
    result = calculate_signal(
        current=ValuationSnapshot(trade_date="2026-05-17", pe=10, pb=10),
        history=_history(pe=[10, 20, 30], pb=[10, 20, 30]),
        category="cn_broad",
        rules=_rules(minimum_observations=3, base_amount=1000),
    )

    assert result.valuation_zone == "合理"
    assert result.dca_ratio == 1.0
    assert result.suggested_amount == 1000


def test_missing_composite_produces_non_actionable_result() -> None:
    result = calculate_signal(
        current=ValuationSnapshot(trade_date="2026-05-17", pe=None, pb=None),
        history=_history(pe=[None, None, None], pb=[None, None, None]),
        category="cn_broad",
        rules=_rules(minimum_observations=3),
    )

    assert result.composite_percentile is None
    assert result.valuation_zone == NON_ACTIONABLE_ZONE
    assert result.dca_ratio == 0
    assert result.suggested_amount == 0


def test_signal_quality_is_complete_when_all_weighted_metrics_have_percentiles() -> None:
    result = calculate_signal(
        current=ValuationSnapshot(trade_date="2026-05-17", pe=10, pb=10),
        history=_history(pe=[10, 20, 30], pb=[10, 20, 30]),
        category="cn_broad",
        rules=_rules(minimum_observations=3),
    )

    assert result.signal_quality == "complete"


def test_signal_quality_is_insufficient_history_below_threshold() -> None:
    result = calculate_signal(
        current=ValuationSnapshot(trade_date="2026-05-17", pe=10, pb=10),
        history=_history(pe=[10, 20], pb=[10, 20]),
        category="cn_broad",
        rules=_rules(minimum_observations=3),
    )

    assert result.signal_quality == "insufficient_history"
    assert result.valuation_zone == NON_ACTIONABLE_ZONE


def test_signal_quality_is_partial_when_configured_metric_is_missing() -> None:
    result = calculate_signal(
        current=ValuationSnapshot(trade_date="2026-05-17", pe=10, pb=None),
        history=_history(pe=[10, 20, 30], pb=[None, None, None]),
        category="cn_broad",
        rules=_rules(minimum_observations=3),
    )

    assert result.signal_quality == "partial"
    assert result.composite_percentile == 33.33


def test_signal_quality_is_partial_when_fallback_usage_is_marked() -> None:
    result = calculate_signal(
        current=ValuationSnapshot(trade_date="2026-05-17", pe=10, pb=10),
        history=_history(pe=[10, 20, 30], pb=[10, 20, 30]),
        category="cn_broad",
        rules=_rules(minimum_observations=3),
        used_fallback=True,
    )

    assert result.signal_quality == "partial"


def test_fetch_failed_signal_comes_from_explicit_failure_state() -> None:
    result = fetch_failed_signal("2026-05-17", message="provider unavailable")

    assert result.signal_quality == "fetch_failed"
    assert result.valuation_zone == NON_ACTIONABLE_ZONE
    assert result.dca_ratio == 0
    assert result.suggested_amount == 0
    assert result.message == "provider unavailable"


def test_signal_uses_configured_zone_label_exactly() -> None:
    result = calculate_signal(
        current=ValuationSnapshot(trade_date="2026-05-17", pe=10, pb=10),
        history=_history(pe=[10, 20, 30], pb=[10, 20, 30]),
        category="cn_broad",
        rules=_rules(minimum_observations=3),
    )

    assert result.valuation_zone == "合理"


def test_signal_reads_rules_config_weights_and_zones() -> None:
    config = load_app_config()
    history = [
        ValuationSnapshot(trade_date="2026-05-15", pe=10, pb=10),
        ValuationSnapshot(trade_date="2026-05-16", pe=20, pb=20),
        ValuationSnapshot(trade_date="2026-05-17", pe=30, pb=30),
    ]

    result = calculate_signal(
        current=ValuationSnapshot(trade_date="2026-05-17", pe=10, pb=10),
        history=history,
        category="cn_broad",
        rules=_rules_from_config(config.rules, minimum_observations=3),
    )

    assert result.signal_quality == "complete"
    assert result.valuation_zone == "合理"


def test_signal_accepts_current_and_history_without_storage() -> None:
    result = calculate_signal(
        current=ValuationSnapshot(trade_date="2026-05-17", pe=10, pb=10),
        history=_history(pe=[10, 20, 30], pb=[10, 20, 30]),
        category="cn_broad",
        rules=_rules(minimum_observations=3),
    )

    assert result.trade_date == "2026-05-17"


def _history(
    *,
    pe: list[float | None],
    pb: list[float | None],
) -> list[ValuationSnapshot]:
    return [
        ValuationSnapshot(
            trade_date=f"2026-05-{index + 1:02d}",
            pe=pe_value,
            pb=pb[index],
        )
        for index, pe_value in enumerate(pe)
    ]


def _rules(
    *,
    minimum_observations: int = 3,
    base_amount: float = 1000,
) -> RulesConfig:
    return RulesConfig(
        lookback_years=5,
        minimum_observations=minimum_observations,
        base_amount=base_amount,
        metric_weights={
            "cn_broad": {
                "pe": 0.6,
                "pb": 0.4,
            }
        },
        zone_rules=[
            ZoneRule(min=0, max=15, zone="明显低估", dca_ratio=2.0),
            ZoneRule(min=15, max=30, zone="合理偏低", dca_ratio=1.2),
            ZoneRule(min=30, max=60, zone="合理", dca_ratio=1.0),
            ZoneRule(min=60, max=80, zone="合理偏高", dca_ratio=0.5),
            ZoneRule(min=80, max=100, zone="高估", dca_ratio=0.0),
        ],
    )


def _rules_from_config(rules: RulesConfig, *, minimum_observations: int) -> RulesConfig:
    return RulesConfig(
        lookback_years=rules.lookback_years,
        minimum_observations=minimum_observations,
        base_amount=rules.base_amount,
        metric_weights=rules.metric_weights,
        zone_rules=rules.zone_rules,
    )
