# Index DCA Alert

Index DCA Alert is a minimal valuation-percentile and dollar-cost averaging
reminder system for broad-market indices.

The MVP is designed to run on GitHub Actions, store historical valuation data in
SQLite, calculate 5-year valuation percentiles, and send Telegram and Feishu Bot
notifications when configured rules produce a DCA signal.

> Status: MVP is runnable locally for the China A-share release path. The
> release gate currently covers CSI 300 (`000300`) and CSI 500 (`000905`) with
> native AKShare Legulegu PE/PB valuation history.

## Why This Exists

Most scheduled investing reminders are either fixed-calendar reminders or
manual spreadsheets. This project adds a simple valuation layer: it compares an
index's current valuation metrics with its recent history, converts that into a
percentile, and adjusts a fixed base DCA amount according to configured rules.

Signals are reminders generated from rules, not personalized investment advice.

## MVP Scope

- MVP release gate:
  - CSI 300
  - CSI 500
- Roadmap indices configured for later provider work:
  - Hang Seng Index
  - Hang Seng TECH Index
  - S&P 500
  - Nasdaq 100
- 5-year valuation percentile window.
- Fixed MVP base amount: `1000`.
- SQLite persistence in `data/index_dca.sqlite`.
- GitHub Actions scheduling after market close.
- Telegram and Feishu Bot notification channels when configured.
- Free data-source strategy only.

Out of scope for the MVP:

- Web UI.
- SMS notifications.
- Paid data providers.
- Web UI for multi-user subscription management (data layer is supported).
- PostgreSQL or hosted service deployment.
- HK/US provider release gates.

## How It Works

```text
GitHub Actions schedule
  -> Python daily job
  -> market window check
  -> fetch index valuation data
  -> upsert SQLite valuation history
  -> calculate 5-year valuation percentiles
  -> generate DCA signal
  -> dispatch notifications (Telegram / Feishu)
  -> record notification status
  -> commit SQLite state back to the repository
```

Scheduled jobs must be idempotent. A fallback run exits early if the same market
and trade date were already processed successfully.

## Supported Indices

| Market | Index | Code | Category | Primary metrics |
| --- | --- | --- | --- | --- |
| China A | CSI 300 | `000300` | `cn_broad` | PE, PB |
| China A | CSI 500 | `000905` | `cn_broad` | PE, PB |
| Hong Kong | Hang Seng Index | `HSI` | `hk_broad` | PE, PB, dividend yield |
| Hong Kong | Hang Seng TECH Index | `HSTECH` | `hk_growth_broad` | PE, PB, price percentile |
| United States | S&P 500 | `SPX` | `us_broad` | PE, CAPE fallback, price percentile |
| United States | Nasdaq 100 | `NDX` | `us_growth_broad` | PE, price percentile, PB if available |

Index metadata lives in [config/indices.yml](/home/ac/Project/PythonWorksPaces/index-dca-alert/config/indices.yml).
Scoring rules live in [config/rules.yml](/home/ac/Project/PythonWorksPaces/index-dca-alert/config/rules.yml).

## Tech Stack

- Python 3.11+.
- `uv` for dependency and project management.
- SQLite for MVP persistence.
- GitHub Actions for scheduling.
- Telegram Bot API for notifications.
- Runtime libraries planned for provider and HTTP work:
  `akshare`, `cryptography`, `pandas`, `pyyaml`, `requests`, and `yfinance`.

The project should migrate dependency configuration to `pyproject.toml` and
`uv.lock`. Avoid adding new dependencies to `requirements.txt`.

## Repository Layout

```text
app/
  schema.sql              SQLite schema.

config/
  indices.yml             Supported index metadata.
  rules.yml               Metric weights, thresholds, and DCA zones.

docs/
  README.md               Documentation map and rules.
  app-foundation/         Python package, project metadata, and config loading.
  runtime/                Scheduling, GitHub Actions, market runs.
  storage/                SQLite schema and persistence rules.
  data-providers/         Provider assumptions and backfill design.
  valuation-signals/      Percentile and DCA signal rules.
  notifications/          Versioned Telegram notification design.
  mvp-release/            Release checklist and smoke test.

templates/
  telegram_signal.md      Telegram message template.
```

Each feature documentation directory contains a feature README and versioned
planning files:

```text
README.md
mvp/
  plan.md
  test.md
  todo.md
```

Later iterations should add sibling version directories such as `v2/` instead
of mixing new plans into completed MVP docs.

Start with [docs/README.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/README.md)
for the documentation map.

## Local Setup

Install `uv` first if it is not already available:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Install dependencies with:

```bash
uv sync
```

Run the foundation test suite with:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests
```

## Configuration

Local secrets should be placed in `.env`, which must not be committed.

Required secrets (in `.env` or GitHub Actions Secrets):

```text
APP_CREDENTIAL_KEY=... (32-byte base64url encoded Fernet key)
TG_BOT_TOKEN=...
TG_CHAT_ID=...
```

In GitHub Actions, configure these as repository secrets:

- `APP_CREDENTIAL_KEY`
- `TG_BOT_TOKEN`
- `TG_CHAT_ID`

## Local MVP Run

Use a throwaway local database for release smoke tests:

```bash
export DB=data/local_mvp_release.sqlite
```

Backfill the CN release-gate indices with five years of native valuation
history:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m app.jobs.backfill \
  --market CN \
  --years 5 \
  --db-path "$DB"
```

Run the daily runtime path locally:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m app.jobs.daily_run \
  --market CN \
  --run-type manual \
  --force \
  --db-path "$DB"
```

For the full release smoke checklist, including SQL checks for persisted
history, PE/PB values, manual percentile verification, idempotency, and
Telegram notification status, follow
[docs/mvp-release/mvp/test.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/mvp-release/mvp/test.md).

## GitHub Actions

The initial workflow is in
[.github/workflows/index-dca-alert.yml](/home/ac/Project/PythonWorksPaces/index-dca-alert/.github/workflows/index-dca-alert.yml).

The target schedule runs after China/Hong Kong and US market close windows, with
fallback runs for delayed provider availability. The current release gate is the
CN path; HK/US configured indices remain roadmap items until their providers are
implemented.

### Deployment Verification

Before the first scheduled run, configure repository secrets under
`Settings -> Secrets and variables -> Actions`:

- `APP_CREDENTIAL_KEY`
- `TG_BOT_TOKEN`
- `TG_CHAT_ID`

Then enable repository write permissions for workflow commits:

```text
Settings -> Actions -> General -> Workflow permissions -> Read and write permissions
```

Manually run the workflow from:

```text
Actions -> index-dca-alert -> Run workflow
```

The first run should complete the `daily` job and print either a successful
runtime result or an idempotent skip:

```text
success: CN <date> processed=2 signals=2 notifications_sent=<count>
skipped: CN <date> already succeeded
```

Validate these outcomes:

- Telegram/Feishu receives the CN signal messages when secrets are configured.
- The SQLite commit step either pushes `chore: update valuation data` or prints
  `No data changes`.
- Running the workflow a second time for the same market date should skip
  duplicate processing and avoid duplicate notifications.
- No `.env`, tokens, chat IDs, or private values appear in commits or logs.

Common failure checks:

- `Unauthorized` or `chat not found`: verify the bot token, chat ID, and bot
  permissions.
- `Permission denied to github-actions[bot]`: verify workflow write
  permissions.
- `NameResolutionError` or provider timeout: retry after the data source is
  reachable.
- `uv sync --frozen` failure: regenerate and commit `uv.lock` from a clean local
  sync.

## Testing

Tests are documented next to each feature:

- [docs/runtime/mvp/test.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/runtime/mvp/test.md)
- [docs/app-foundation/mvp/test.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/app-foundation/mvp/test.md)
- [docs/storage/mvp/test.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/storage/mvp/test.md)
- [docs/data-providers/mvp/test.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/data-providers/mvp/test.md)
- [docs/valuation-signals/mvp/test.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/valuation-signals/mvp/test.md)
- [docs/notifications/mvp/test.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/notifications/mvp/test.md)
- [docs/mvp-release/mvp/test.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/mvp-release/mvp/test.md)

Normal tests should use local fixtures and avoid live provider or Telegram API
calls. Live checks should be manual or explicitly marked.

## Data and Secrets

- Treat `data/index_dca.sqlite` as stateful MVP data.
- GitHub Actions may commit SQLite state back to the repository.
- Never commit `.env`, tokens, chat IDs, or other private credentials.
- Do not silently mix native index valuation data with ETF proxy fundamentals.
  Preserve `source`, `source_type`, and `metric_schema_version`.

## Development Guidelines

- Follow the feature TODO lists under `docs/<feature>/<version>/todo.md`.
- Keep feature plans, tests, and TODOs in the same versioned feature
  documentation directory.
- Use lightweight DDD driven by real business concepts, not directory templates.
- Prefer interface boundaries for providers, repositories, scoring services, and
  notification channels.
- Use UUIDv4 text primary keys for all application tables.
- Commit completed functional workstreams with clear Conventional Commit
  messages, for example:

```text
feat: add daily valuation job
fix: make market run idempotent
docs: refine provider backfill plan
test: cover percentile boundary rules
```

## License

No license has been selected yet.
