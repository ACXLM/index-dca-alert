# MVP Release Plan

## Goal

Prove that the runnable MVP works end to end on local SQLite and GitHub Actions:
configuration loading, schema initialization, CN historical backfill, valuation
signal calculation, Telegram notification dispatch, runtime idempotency, and
SQLite state persistence.

## Release Scope

The release gate is the currently runnable MVP path:

- China A-share market only.
- CSI 300 (`000300`) and CSI 500 (`000905`).
- Native index valuation data from AKShare Legulegu PE/PB history.
- Five-year percentile window from SQLite history.
- Fixed default base amount from `config/rules.yml`, currently `1000`.
- Telegram Bot notification when `TG_BOT_TOKEN` and `TG_CHAT_ID` are available.
- GitHub Actions schedule and no-op-safe SQLite commit.

The following indices are configured for roadmap continuity but are not release
gates until their providers are implemented:

- HSI
- HSTECH
- SPX
- NDX

## Release Gates

### Data Coverage

- CN backfill must persist roughly five years of rows for both `000300` and
  `000905`.
- CN valuation rows must use `source = "akshare_legulegu_index"` for release
  signal calculations.
- Recent-window CSI valuation files must not be accepted as successful CN DCA
  signal history.
- PE and PB should be present for the latest available CN valuation rows.
- If a source cannot provide enough history, the run should fail closed or
  produce non-actionable signal quality, not a confident recommendation.

### Storage

- SQLite schema initializes from `app/schema.sql`.
- Indices and DCA rules seed idempotently.
- Valuations upsert by `(index_id, trade_date, source)`.
- Signals upsert by `(user_subscription_id, trade_date)`.
- Notification attempts remain append-only.
- `market_runs` prevents duplicate same-market same-date fallback processing.

### Runtime

- `app.jobs.daily_run` runs the CN path with `--market CN`.
- Without `--force`, a successful same-market same-date run causes later
  fallback runs to print `skipped` and avoid writing new `market_runs` rows.
- With `--force`, manual local repair runs can re-run signal and notification
  generation intentionally.
- Backfill uses SQLite coverage to avoid re-fetching a fully cached window.
- When only the tail is missing, backfill requests only the missing tail window.
- `--refresh` explicitly bypasses the local coverage cache.

### Notifications

- Local `.env` may contain `TG_BOT_TOKEN` and `TG_CHAT_ID`; it must never be
  committed.
- `daily_run` loads `.env` for local runs.
- If Telegram config is missing, runtime still writes signals and skips
  notification dispatch.
- If Telegram config is present, runtime records one notification attempt per
  dispatched signal.
- Notification status is stored as separate `status`, `error_message`, and
  `sent_at` fields.

### GitHub Actions

- Workflow installs dependencies with `uv sync --frozen`.
- Workflow runs `uv run python -m app.jobs.daily_run`.
- Telegram secrets come from GitHub Actions secrets.
- The SQLite commit step succeeds when there are no data changes.

## Non-Goals

- No web UI.
- No SMS channel.
- No paid data source.
- No ORM.
- No background worker or service daemon.
- No committed secrets or private `.env` values.
- No HK/US provider release gate until those adapters are implemented.
