# MVP Release Tests

## Automated Tests

Run the full deterministic suite:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests
```

Expected result:

- All tests pass.
- No normal test performs live provider or Telegram calls.

## Local Smoke Test

Use a local throwaway database:

```bash
export DB=data/local_mvp_release.sqlite
```

### Backfill CN History

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m app.jobs.backfill \
  --market CN \
  --years 5 \
  --db-path "$DB"
```

Verify persisted history:

```bash
sqlite3 "$DB" '
SELECT i.code, i.name, COUNT(*) AS rows, MIN(v.trade_date) AS first_date,
       MAX(v.trade_date) AS last_date, GROUP_CONCAT(DISTINCT v.source) AS sources
FROM index_valuations v
JOIN indices i ON i.id = v.index_id
WHERE i.market = "CN"
GROUP BY i.code, i.name;
'
```

Expected result:

- `000300` and `000905` are present.
- Each CN index has roughly five years of trading-day rows.
- `first_date` is near the configured five-year lookback start.
- `last_date` is the latest available trade date.
- `sources` is `akshare_legulegu_index`.

Verify latest PE/PB:

```bash
sqlite3 "$DB" '
SELECT i.code, v.trade_date, v.pe, v.pb, v.close, v.source, v.source_type
FROM index_valuations v
JOIN indices i ON i.id = v.index_id
WHERE i.market = "CN"
  AND v.trade_date = (
    SELECT MAX(v2.trade_date)
    FROM index_valuations v2
    WHERE v2.index_id = v.index_id
  )
ORDER BY i.code;
'
```

Expected result:

- Latest rows have positive PE and PB values.
- `source_type = native_index`.

### Verify Manual Percentile

Manually calculate the PE percentile for CSI 300:

```bash
sqlite3 "$DB" '
WITH latest AS (
  SELECT v.*
  FROM index_valuations v
  JOIN indices i ON i.id = v.index_id
  WHERE i.code = "000300"
  ORDER BY v.trade_date DESC
  LIMIT 1
),
hist AS (
  SELECT v.pe
  FROM index_valuations v
  JOIN indices i ON i.id = v.index_id
  WHERE i.code = "000300"
    AND v.pe IS NOT NULL
    AND v.pe > 0
    AND v.trade_date <= (SELECT trade_date FROM latest)
)
SELECT (SELECT trade_date FROM latest) AS latest_date,
       (SELECT pe FROM latest) AS latest_pe,
       COUNT(*) AS observation_count,
       ROUND(SUM(CASE WHEN pe <= (SELECT pe FROM latest) THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2)
         AS manual_pe_percentile
FROM hist;
'
```

After running daily runtime, compare this value with
`valuation_signals.pe_percentile`.

### Run Daily Runtime Without Telegram

Run with Telegram config absent from the shell and `.env` if you want to verify
the no-notification path:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m app.jobs.daily_run \
  --market CN \
  --run-type manual \
  --force \
  --db-path "$DB"
```

Verify signals:

```bash
sqlite3 "$DB" '
SELECT i.code, s.trade_date, s.pe_percentile, s.pb_percentile,
       s.composite_percentile, s.signal_quality, s.valuation_zone,
       s.dca_ratio, s.suggested_amount
FROM valuation_signals s
JOIN indices i ON i.id = s.index_id
ORDER BY i.code, s.trade_date DESC;
'
```

Expected result:

- One current signal for `000300`.
- One current signal for `000905`.
- `signal_quality` is `complete` when enough valid PE/PB observations exist.
- Suggested amount matches `base_amount * dca_ratio`.

Verify notification absence:

```bash
sqlite3 "$DB" 'SELECT COUNT(*) AS notification_count FROM notifications;'
```

Expected result:

- No notification rows if Telegram config is unavailable or `--dry-run` was
  used.

### Run Daily Runtime With Telegram

Create a local `.env` with real values:

```bash
TG_BOT_TOKEN=...
TG_CHAT_ID=...
```

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m app.jobs.daily_run \
  --market CN \
  --run-type manual \
  --force \
  --db-path "$DB"
```

Verify notification attempts:

```bash
sqlite3 "$DB" '
SELECT channel, target, status, error_message, sent_at, created_at
FROM notifications
ORDER BY created_at DESC
LIMIT 10;
'
```

Expected result:

- `status = sent` when Telegram accepts the message.
- `status = failed` with sanitized `error_message` when Telegram rejects or
  network fails.
- Token values must not appear in `error_message`.

### Verify Runtime Idempotency

Run once without `--force` after a successful market/date run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m app.jobs.daily_run \
  --market CN \
  --run-type fallback \
  --db-path "$DB"
```

Expected result:

- stdout prints `skipped`.
- No new fallback `market_runs` row is inserted.

Check:

```bash
sqlite3 "$DB" '
SELECT market, trade_date, run_type, status, error_message
FROM market_runs
ORDER BY started_at DESC;
'
```

### Verify Backfill Cache

Run the same backfill command twice:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m app.jobs.backfill \
  --market CN \
  --years 5 \
  --db-path "$DB"
```

Expected result:

- The second run should not call the provider for fully covered CN indices.

For an explicit full refresh:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m app.jobs.backfill \
  --market CN \
  --years 5 \
  --refresh \
  --db-path "$DB"
```

Expected result:

- Provider data is fetched again intentionally.

## GitHub Actions Verification

Inspect `.github/workflows/index-dca-alert.yml`:

- Uses `astral-sh/setup-uv`.
- Runs `uv sync --frozen`.
- Runs `uv run python -m app.jobs.daily_run`.
- Reads `TG_BOT_TOKEN` and `TG_CHAT_ID` from GitHub Actions secrets.
- Uses `git diff --cached --quiet` before committing SQLite state.

## Release Failure Conditions

Treat the release as failed if any of these are true:

- CN history is recent-only or materially below the five-year window.
- CN valuation rows for release signals do not use `akshare_legulegu_index`.
- PE/PB latest values are missing for both CN indices.
- Signal quality is unexpectedly `insufficient_history` after a valid five-year
  backfill.
- Telegram secrets are present but no notification attempt row is created.
- Telegram errors expose tokens or chat IDs in committed logs or database rows.
- Repeated fallback processing creates duplicate same-market same-date runtime
  work without `--force`.
