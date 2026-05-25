# Runtime and Scheduling TODO

- [x] Add CLI entry point for `app.jobs.daily_run`.
- [x] Implement market window detection with `zoneinfo`.
- [x] Handle China and Hong Kong close-after retrieval windows.
- [x] Handle US market close detection across New York daylight saving time.
- [x] Implement weekend skip behavior.
- [x] Infer default trade date from market-local date.
- [x] Add `--market`, `--trade-date`, `--run-type`, `--force`, `--db-path`,
  and `--dry-run` options.
- [x] Make fallback scheduled runs exit early after a successful same-market,
  same-date run.
- [x] Ensure skipped runs only print stdout and do not write `market_runs`.
- [x] Bootstrap default Telegram subscriptions when `TG_CHAT_ID` exists.
- [x] Persist signals through a local-disabled default subscription when
  `TG_CHAT_ID` is missing.
- [x] Skip notification dispatch when Telegram configuration is unavailable.
- [x] Map `SignalResult` fields into storage `SignalInput`.
- [x] Build `NotificationContext` from index, valuation, subscription, and
  signal data.
- [x] Record provider/index-level failures without blocking other market
  indices.
- [x] Mark market runs failed when every selected index fails to produce usable
  valuation data.
- [x] Record unexpected daily-run boundary failures in `market_runs`.
- [x] Validate and finalize GitHub Actions workflow.
- [x] Migrate GitHub Actions dependency installation to `uv`.
- [x] Remove `requirements.txt` workflow usage.
- [x] Make the SQLite commit step no-op safe.
