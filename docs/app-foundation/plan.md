# App Foundation Plan

## Goal

Establish the minimal Python application foundation that every later MVP
feature can depend on: package layout, dependency metadata, configuration
loading, and configuration validation.

This feature exists because these responsibilities cut across storage,
valuation signals, providers, notifications, and runtime jobs. Treating them as
a separate foundation keeps the implementation order clear without turning
phase planning into the long-term documentation structure.

## Scope

App foundation includes:

- Python package structure under `app/`.
- Project dependency and tool metadata with `pyproject.toml` and `uv`.
- Typed configuration loading for `config/indices.yml` and `config/rules.yml`.
- Configuration consistency validation shared by later features.
- A predictable test command for foundation tests.

App foundation does not include:

- SQLite initialization or repository implementations.
- Seeding configured indices or DCA rules into SQLite.
- Percentile calculation, composite scoring, or DCA signal generation.
- Provider adapters, historical backfill, or live data fetching.
- Telegram rendering or sending.
- Daily runtime orchestration or GitHub Actions scheduling.

## Package Layout

The foundation should create the shallow MVP package structure:

```text
app/
  __init__.py
  config.py
  jobs/
    __init__.py
  providers/
    __init__.py
  repositories/
    __init__.py
  services/
    __init__.py
```

New modules should be added under the feature directory that owns the behavior.
The foundation should not introduce nested package layers before there is real
complexity.

## Configuration Model

`app.config` should expose typed configuration objects for:

- enabled index metadata from `config/indices.yml`
- rule settings from `config/rules.yml`
- the combined application configuration

The implementation should prefer standard-library `dataclasses` plus `pyyaml`
instead of adding a heavier validation dependency.

Expected concepts:

- `IndexConfig`
- `ZoneRule`
- `RulesConfig`
- `AppConfig`
- `ConfigError`

The config loader should support missing `enabled` on index entries by treating
the index as enabled. This matches the database schema default and keeps the
loader behavior backward compatible.

The MVP index configuration should still declare `enabled: true` explicitly for
each supported index so the active runtime set is visible in the YAML file.

## Validation Rules

Foundation validation should prove the configuration is internally consistent
before later features depend on it:

- every enabled index category has configured metric weights
- `base_amount` is greater than zero
- `lookback_years` is greater than zero
- `minimum_observations` is greater than zero
- every metric weight is greater than zero
- each category's metric weight total is greater than zero
- every zone rule has `min < max`
- zone rules are continuous, non-overlapping, and cover `0` through `100`
- every zone rule has `dca_ratio >= 0`

These checks are intentionally configuration-level checks. Runtime behavior such
as percentile calculation, score quality, and DCA amount selection belongs to
`valuation-signals`.

## Relationship to Other Features

`storage` will later use the same configuration loader to seed indices and DCA
rules, but seeding itself belongs to storage.

`valuation-signals` will later use the loaded rule configuration to calculate
percentiles, composite scores, signal quality, and DCA ratios.

`runtime` will later use the package structure and loaded configuration to run
CLI jobs such as `app.jobs.daily_run` and `app.jobs.backfill`.
