# Data Providers Tests

## Unit Tests

- Provider normalization maps local fixture fields into canonical valuation
  fields.
- AKShare CSI rows preserve metric schema interpretation.
- AKShare Legulegu PE/PB rows merge into canonical 5-year valuation rows.
- China index provider uses Legulegu PE/PB history instead of recent-window CSI
  valuation files.
- China index provider raises a provider failure when only recent-window
  history is available.
- ETF proxy rows preserve `source_type = etf_proxy`.
- Missing optional fields are represented as missing data, not zero values.
- Invalid rows with missing `trade_date` or no positive metric/close are not
  normalized into valuation rows.
- Provider failures raise clear errors and do not produce valid-looking rows.
- Provider adapters do not write SQLite directly.

## Integration Tests

- Backfill is idempotent for repeated runs.
- Repeated backfill does not duplicate `index_valuations` rows.
- Coverage gaps are recorded in `data_quality_events`.
- Provider failures are recorded in `data_quality_events` when appropriate.
- Invalid rows are skipped and recorded in `data_quality_events`.
- Historical rows preserve `source`, `source_type`, and
  `metric_schema_version`.
- Backfill initializes SQLite and seeds indices/rules before writing
  valuations.
- Backfill applies `--market`, `--index-code`, `--years`, and `--db-path`
  arguments deterministically.
- Backfill writes the configured 5-year China index history from Legulegu even
  when CSI valuation files only contain recent-window rows.
- Backfill does not persist recent-only China valuation rows as usable history.
- Backfill does not call signal calculation or notification code.
- One index provider failure does not remove already committed rows for another
  index.

## External Calls

Normal tests should not call live providers. Use local fixtures by default.
Live provider checks should be manual or explicitly marked.
