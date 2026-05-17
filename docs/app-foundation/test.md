# App Foundation Test Plan

## Unit Tests

Foundation tests should be deterministic and should not call live providers,
Telegram, or GitHub Actions.

Required tests:

- load the current `config/indices.yml` and `config/rules.yml` successfully
- verify the real MVP index config declares explicit `enabled` fields
- default a missing index `enabled` field to enabled
- reject an enabled index category that has no metric weights
- reject non-positive `base_amount`
- reject non-positive `lookback_years`
- reject non-positive `minimum_observations`
- reject zero or negative metric weights
- reject zone rules with gaps
- reject zone rules with overlaps
- reject zone rules that do not cover the full `0` to `100` range
- reject a zone rule where `min >= max`
- reject a negative `dca_ratio`

## Fixture Strategy

Tests should use small inline dictionaries or temporary YAML files. They should
not mutate the real files under `config/`.

The real config files should have one smoke-style test that loads them as-is so
configuration drift is caught early.

## Manual Verification

Manual verification for this feature is limited to running the foundation test
suite through `uv`.

Expected command:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests
```
