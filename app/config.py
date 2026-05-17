from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDICES_PATH = PROJECT_ROOT / "config" / "indices.yml"
DEFAULT_RULES_PATH = PROJECT_ROOT / "config" / "rules.yml"


class ConfigError(ValueError):
    """Raised when application configuration is missing or inconsistent."""


@dataclass(frozen=True)
class IndexConfig:
    code: str
    name: str
    market: str
    category: str
    currency: str
    timezone: str
    primary_provider: str
    source_symbol: str
    enabled: bool = True


@dataclass(frozen=True)
class ZoneRule:
    min: float
    max: float
    zone: str
    dca_ratio: float


@dataclass(frozen=True)
class RulesConfig:
    lookback_years: int
    minimum_observations: int
    base_amount: float
    metric_weights: dict[str, dict[str, float]]
    zone_rules: list[ZoneRule]


@dataclass(frozen=True)
class AppConfig:
    indices: list[IndexConfig]
    rules: RulesConfig

    @property
    def enabled_indices(self) -> list[IndexConfig]:
        return [index for index in self.indices if index.enabled]


def load_app_config(
    indices_path: str | Path = DEFAULT_INDICES_PATH,
    rules_path: str | Path = DEFAULT_RULES_PATH,
) -> AppConfig:
    indices = load_indices_config(indices_path)
    rules = load_rules_config(rules_path)
    config = AppConfig(indices=indices, rules=rules)
    validate_app_config(config)
    return config


def load_indices_config(path: str | Path = DEFAULT_INDICES_PATH) -> list[IndexConfig]:
    data = _load_yaml_mapping(path)
    raw_indices = data.get("indices")
    if not isinstance(raw_indices, list):
        raise ConfigError("indices.yml must contain an 'indices' list")
    return [_parse_index_config(item, index) for index, item in enumerate(raw_indices)]


def load_rules_config(path: str | Path = DEFAULT_RULES_PATH) -> RulesConfig:
    data = _load_yaml_mapping(path)
    try:
        zone_rules = [_parse_zone_rule(item, index) for index, item in enumerate(data["zone_rules"])]
        rules = RulesConfig(
            lookback_years=int(data["lookback_years"]),
            minimum_observations=int(data["minimum_observations"]),
            base_amount=float(data["base_amount"]),
            metric_weights=_parse_metric_weights(data["metric_weights"]),
            zone_rules=zone_rules,
        )
    except KeyError as exc:
        raise ConfigError(f"rules.yml missing required key: {exc.args[0]}") from exc
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"rules.yml contains invalid values: {exc}") from exc
    validate_rules_config(rules)
    return rules


def validate_app_config(config: AppConfig) -> None:
    enabled_categories = {index.category for index in config.enabled_indices}
    missing_categories = sorted(
        category for category in enabled_categories if category not in config.rules.metric_weights
    )
    if missing_categories:
        joined = ", ".join(missing_categories)
        raise ConfigError(f"enabled index categories missing metric weights: {joined}")


def validate_rules_config(rules: RulesConfig) -> None:
    if rules.base_amount <= 0:
        raise ConfigError("base_amount must be greater than zero")
    if rules.lookback_years <= 0:
        raise ConfigError("lookback_years must be greater than zero")
    if rules.minimum_observations <= 0:
        raise ConfigError("minimum_observations must be greater than zero")
    _validate_metric_weights(rules.metric_weights)
    _validate_zone_rules(rules.zone_rules)


def _load_yaml_mapping(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"failed to read config file {config_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"failed to parse YAML config file {config_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config file {config_path} must contain a mapping")
    return data


def _parse_index_config(item: Any, index: int) -> IndexConfig:
    if not isinstance(item, dict):
        raise ConfigError(f"indices[{index}] must be a mapping")
    try:
        return IndexConfig(
            code=str(item["code"]),
            name=str(item["name"]),
            market=str(item["market"]),
            category=str(item["category"]),
            currency=str(item["currency"]),
            timezone=str(item["timezone"]),
            primary_provider=str(item["primary_provider"]),
            source_symbol=str(item["source_symbol"]),
            enabled=bool(item.get("enabled", True)),
        )
    except KeyError as exc:
        raise ConfigError(f"indices[{index}] missing required key: {exc.args[0]}") from exc


def _parse_zone_rule(item: Any, index: int) -> ZoneRule:
    if not isinstance(item, dict):
        raise ConfigError(f"zone_rules[{index}] must be a mapping")
    try:
        return ZoneRule(
            min=float(item["min"]),
            max=float(item["max"]),
            zone=str(item["zone"]),
            dca_ratio=float(item["dca_ratio"]),
        )
    except KeyError as exc:
        raise ConfigError(f"zone_rules[{index}] missing required key: {exc.args[0]}") from exc


def _parse_metric_weights(raw_weights: Any) -> dict[str, dict[str, float]]:
    if not isinstance(raw_weights, dict):
        raise ConfigError("metric_weights must be a mapping")
    metric_weights: dict[str, dict[str, float]] = {}
    for category, weights in raw_weights.items():
        if not isinstance(weights, dict):
            raise ConfigError(f"metric_weights.{category} must be a mapping")
        metric_weights[str(category)] = {
            str(metric): float(weight) for metric, weight in weights.items()
        }
    return metric_weights


def _validate_metric_weights(metric_weights: dict[str, dict[str, float]]) -> None:
    if not metric_weights:
        raise ConfigError("metric_weights must not be empty")
    for category, weights in metric_weights.items():
        if not weights:
            raise ConfigError(f"metric_weights.{category} must not be empty")
        total = 0.0
        for metric, weight in weights.items():
            if weight <= 0:
                raise ConfigError(f"metric_weights.{category}.{metric} must be greater than zero")
            total += weight
        if total <= 0:
            raise ConfigError(f"metric_weights.{category} total must be greater than zero")


def _validate_zone_rules(zone_rules: list[ZoneRule]) -> None:
    if not zone_rules:
        raise ConfigError("zone_rules must not be empty")
    sorted_rules = sorted(zone_rules, key=lambda rule: rule.min)
    expected_min = 0.0
    for rule in sorted_rules:
        if rule.min >= rule.max:
            raise ConfigError(f"zone rule '{rule.zone}' must have min lower than max")
        if rule.dca_ratio < 0:
            raise ConfigError(f"zone rule '{rule.zone}' dca_ratio must not be negative")
        if rule.min != expected_min:
            raise ConfigError("zone_rules must be continuous, non-overlapping, and start at 0")
        expected_min = rule.max
    if expected_min != 100.0:
        raise ConfigError("zone_rules must cover through 100")
