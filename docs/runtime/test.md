# Runtime and Scheduling Tests

## Unit Tests

- China local market-window detection handles normal weekdays after close.
- Hong Kong local market-window detection handles normal weekdays after close.
- Pre-close China and Hong Kong windows do not run.
- US market-window detection handles New York daylight saving time.
- US market-window detection handles New York standard time.
- Weekend market-window checks do not run.
- Default trade date uses market-local date.
- `--trade-date` overrides inferred market-local date.
- `--force` skips market-window checks.
- Unknown or unsupported market values fail with a clear error.

## Integration Tests

- A fallback scheduled run exits when any successful `market_runs` row already
  exists for the same market and trade date, even when run type differs.
- Skipped runs print a clear message and do not insert `market_runs` rows.
- Daily update writes at most one signal per subscription and trade date.
- Daily update maps all signal percentile fields into `valuation_signals`.
- Daily update bootstraps a default subscription with `notify_target =
  "local-disabled"` when `TG_CHAT_ID` is missing, so signals are still
  persisted.
- Daily update bootstraps default Telegram subscriptions with `TG_CHAT_ID` when
  Telegram configuration is available.
- Daily update skips notification dispatch when `TG_CHAT_ID` is missing.
- Daily update dispatches notifications through a fake channel in tests and
  records notification attempts.
- Provider failure for one index does not block another index in the same
  market.
- If every index in the selected market fails to produce usable valuation data,
  the market run is marked `failed`.
- Failed runs record status and error details without marking the market run as
  successful.
- `--dry-run` does not send Telegram or record durable notification attempts.
- GitHub Actions workflow uses `uv`, does not install `requirements.txt`, and
  has a no-op-safe SQLite commit step.

## Manual Verification

- Trigger the workflow manually from GitHub Actions.
- Confirm the job uses `uv` commands after packaging migration.
- Confirm unchanged SQLite state does not create a failing commit step.
- Run `daily_run --market CN --force --db-path data/index_dca.sqlite` locally.
