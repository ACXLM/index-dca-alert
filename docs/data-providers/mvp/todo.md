# Data Providers TODO

- [x] Add CLI entry point for `app.jobs.backfill`.
- [x] Define provider interfaces and canonical `ProviderValuation` output.
- [x] Define `ProviderError` for source and normalization failures.
- [x] Implement AKShare provider for CSI 300 and CSI 500.
- [x] Prefer AKShare Legulegu PE/PB history for China 5-year backfill.
- [x] Reject recent-only China valuation data instead of using it for signals.
- [x] Keep AKShare CSI valuation files out of China DCA signal fallback paths.
- [x] Normalize AKShare CSI fixture rows into canonical valuation fields.
- [x] Normalize AKShare Legulegu PE/PB rows into canonical valuation fields.
- [x] Validate provider rows and skip invalid rows without producing
  valid-looking valuations.
- [x] Resolve providers from `primary_provider` in `config/indices.yml`.
- [x] Implement backfill CLI filters for `--market`, `--index-code`,
  `--years`, and `--db-path`.
- [x] Skip provider calls when SQLite already covers the requested lookback
  window.
- [x] Fetch only the missing tail when SQLite already has the lookback start.
- [x] Refetch the full window when SQLite is missing the lookback start.
- [x] Add `--refresh` to explicitly bypass the local coverage cache.
- [ ] Implement Hong Kong provider adapter.
- [ ] Define exact HSI and HSTECH ticker/fallback symbols.
- [ ] Implement US provider adapters for SPX and NDX.
- [x] Implement historical backfill command with a 5-year default lookback.
- [x] Record provider failures and coverage gaps in `data_quality_events`.
- [x] Preserve `source`, `source_type`, and `metric_schema_version` for every
  valuation row.
- [x] Keep signal calculation, notifications, and market-window scheduling out
  of provider/backfill code.
- [x] Add fixture-based provider and backfill tests with no live provider calls
  by default.
