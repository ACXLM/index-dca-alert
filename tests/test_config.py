from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from app.config import ConfigError, load_app_config, load_indices_config, load_rules_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_loads_real_project_config() -> None:
    config = load_app_config()

    assert len(config.indices) == 6
    assert len(config.enabled_indices) == 6
    assert config.rules.base_amount == 1000


def test_real_mvp_indices_declare_enabled_fields() -> None:
    data = yaml.safe_load((PROJECT_ROOT / "config" / "indices.yml").read_text(encoding="utf-8"))

    assert all("enabled" in item for item in data["indices"])


def test_missing_enabled_defaults_to_enabled(tmp_path: Path) -> None:
    indices_path = tmp_path / "indices.yml"
    data = _valid_indices_data()
    data["indices"][0].pop("enabled")
    indices_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    indices = load_indices_config(indices_path)

    assert indices[0].enabled is True


def test_rejects_enabled_index_category_without_metric_weights(tmp_path: Path) -> None:
    indices_path, rules_path = _write_config(tmp_path)
    rules = _valid_rules_data()
    rules["metric_weights"] = {"other_category": {"pe": 1.0}}
    rules_path.write_text(yaml.safe_dump(rules), encoding="utf-8")

    with pytest.raises(ConfigError, match="missing metric weights"):
        load_app_config(indices_path, rules_path)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("base_amount", 0, "base_amount"),
        ("lookback_years", 0, "lookback_years"),
        ("minimum_observations", 0, "minimum_observations"),
    ],
)
def test_rejects_non_positive_rule_settings(
    tmp_path: Path,
    key: str,
    value: int,
    message: str,
) -> None:
    rules_path = tmp_path / "rules.yml"
    rules = _valid_rules_data()
    rules[key] = value
    rules_path.write_text(yaml.safe_dump(rules), encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        load_rules_config(rules_path)


@pytest.mark.parametrize("weight", [0, -0.1])
def test_rejects_zero_or_negative_metric_weights(tmp_path: Path, weight: float) -> None:
    rules_path = tmp_path / "rules.yml"
    rules = _valid_rules_data()
    rules["metric_weights"]["cn_broad"]["pe"] = weight
    rules_path.write_text(yaml.safe_dump(rules), encoding="utf-8")

    with pytest.raises(ConfigError, match="must be greater than zero"):
        load_rules_config(rules_path)


def test_rejects_zone_rule_gaps(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules.yml"
    rules = _valid_rules_data()
    rules["zone_rules"][1]["min"] = 20
    rules_path.write_text(yaml.safe_dump(rules), encoding="utf-8")

    with pytest.raises(ConfigError, match="continuous"):
        load_rules_config(rules_path)


def test_rejects_zone_rule_overlaps(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules.yml"
    rules = _valid_rules_data()
    rules["zone_rules"][1]["min"] = 10
    rules_path.write_text(yaml.safe_dump(rules), encoding="utf-8")

    with pytest.raises(ConfigError, match="continuous"):
        load_rules_config(rules_path)


def test_rejects_zone_rules_that_do_not_cover_full_range(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules.yml"
    rules = _valid_rules_data()
    rules["zone_rules"][-1]["max"] = 90
    rules_path.write_text(yaml.safe_dump(rules), encoding="utf-8")

    with pytest.raises(ConfigError, match="cover through 100"):
        load_rules_config(rules_path)


def test_rejects_zone_rule_with_min_greater_than_or_equal_to_max(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules.yml"
    rules = _valid_rules_data()
    rules["zone_rules"][0]["min"] = 15
    rules_path.write_text(yaml.safe_dump(rules), encoding="utf-8")

    with pytest.raises(ConfigError, match="min lower than max"):
        load_rules_config(rules_path)


def test_rejects_negative_dca_ratio(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules.yml"
    rules = _valid_rules_data()
    rules["zone_rules"][0]["dca_ratio"] = -1
    rules_path.write_text(yaml.safe_dump(rules), encoding="utf-8")

    with pytest.raises(ConfigError, match="dca_ratio"):
        load_rules_config(rules_path)


def _write_config(tmp_path: Path) -> tuple[Path, Path]:
    indices_path = tmp_path / "indices.yml"
    rules_path = tmp_path / "rules.yml"
    indices_path.write_text(yaml.safe_dump(_valid_indices_data()), encoding="utf-8")
    rules_path.write_text(yaml.safe_dump(_valid_rules_data()), encoding="utf-8")
    return indices_path, rules_path


def _valid_indices_data() -> dict:
    return {
        "indices": [
            {
                "code": "000300",
                "name": "CSI 300",
                "enabled": True,
                "market": "CN",
                "category": "cn_broad",
                "currency": "CNY",
                "timezone": "Asia/Shanghai",
                "primary_provider": "akshare_csindex",
                "source_symbol": "000300",
            }
        ]
    }


def _valid_rules_data() -> dict:
    return deepcopy(
        {
            "lookback_years": 5,
            "minimum_observations": 500,
            "base_amount": 1000,
            "metric_weights": {
                "cn_broad": {
                    "pe": 0.6,
                    "pb": 0.4,
                }
            },
            "zone_rules": [
                {"min": 0, "max": 15, "zone": "clearly_undervalued", "dca_ratio": 2.0},
                {"min": 15, "max": 30, "zone": "mildly_undervalued", "dca_ratio": 1.2},
                {"min": 30, "max": 60, "zone": "fair", "dca_ratio": 1.0},
                {"min": 60, "max": 80, "zone": "mildly_overvalued", "dca_ratio": 0.5},
                {"min": 80, "max": 100, "zone": "overvalued", "dca_ratio": 0.0},
            ],
        }
    )
