# Index DCA Alert

Index DCA Alert is a minimal valuation-percentile and dollar-cost averaging
reminder system for broad-market indices.

The MVP is designed to run on GitHub Actions, store historical valuation data in
SQLite, calculate 5-year valuation percentiles, and send Telegram Bot
notifications when configured rules produce a DCA signal.

> Status: MVP design and scaffolding are in progress. The repository currently
> contains schema, configuration, documentation, templates, and an initial
> workflow shape. Runtime Python jobs are still being implemented.

## Why This Exists

Most scheduled investing reminders are either fixed-calendar reminders or
manual spreadsheets. This project adds a simple valuation layer: it compares an
index's current valuation metrics with its recent history, converts that into a
percentile, and adjusts a fixed base DCA amount according to configured rules.

Signals are reminders generated from rules, not personalized investment advice.

## MVP Scope

- Six broad-market indices:
  - CSI 300
  - CSI 500
  - Hang Seng Index
  - Hang Seng TECH Index
  - S&P 500
  - Nasdaq 100
- 5-year valuation percentile window.
- Fixed MVP base amount: `1000`.
- SQLite persistence in `data/index_dca.sqlite`.
- GitHub Actions scheduling after market close.
- Telegram Bot notification channel.
- Free data-source strategy only.

Out of scope for the MVP:

- Web UI.
- SMS notifications.
- Paid data providers.
- Multi-user subscription management beyond the initial configured flow.
- PostgreSQL or hosted service deployment.

## How It Works

```text
GitHub Actions schedule
  -> Python daily job
  -> market window check
  -> fetch index valuation data
  -> upsert SQLite valuation history
  -> calculate 5-year valuation percentiles
  -> generate DCA signal
  -> render Telegram notification
  -> send Telegram message
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
  `akshare`, `pandas`, `pyyaml`, `requests`, and `yfinance`.

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
  runtime/                Scheduling, GitHub Actions, market runs.
  storage/                SQLite schema and persistence rules.
  data-providers/         Provider assumptions and backfill design.
  valuation-signals/      Percentile and DCA signal rules.
  notifications/          Telegram notification design.
  mvp-release/            Release checklist and smoke test.

templates/
  telegram_signal.md      Telegram message template.
```

Each feature documentation directory contains:

```text
plan.md
test.md
todo.md
```

Start with [docs/README.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/README.md)
for the documentation map.

## Local Setup

Install `uv` first if it is not already available:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Once project packaging is added, install dependencies with:

```bash
uv sync
```

For the current scaffold, dependency migration is still pending. See
[docs/runtime/todo.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/runtime/todo.md)
and [docs/mvp-release/todo.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/mvp-release/todo.md).

## Configuration

Local secrets should be placed in `.env`, which must not be committed.

Required Telegram variables:

```text
TG_BOT_TOKEN=...
TG_CHAT_ID=...
```

In GitHub Actions, configure these as repository secrets:

- `TG_BOT_TOKEN`
- `TG_CHAT_ID`

## Planned Commands

The MVP command surface is planned as:

```bash
uv run python -m app.jobs.backfill --years 5
uv run python -m app.jobs.daily_run
```

These commands are not available until the Python package structure and runtime
jobs are implemented.

## GitHub Actions

The initial workflow is in
[.github/workflows/index-dca-alert.yml](/home/ac/Project/PythonWorksPaces/index-dca-alert/.github/workflows/index-dca-alert.yml).

The target schedule runs after China/Hong Kong and US market close windows, with
fallback runs for delayed provider availability. The workflow currently reflects
the intended shape and still needs to be finalized for `uv`.

## Testing

Tests are documented next to each feature:

- [docs/runtime/test.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/runtime/test.md)
- [docs/storage/test.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/storage/test.md)
- [docs/data-providers/test.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/data-providers/test.md)
- [docs/valuation-signals/test.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/valuation-signals/test.md)
- [docs/notifications/test.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/notifications/test.md)
- [docs/mvp-release/test.md](/home/ac/Project/PythonWorksPaces/index-dca-alert/docs/mvp-release/test.md)

Normal tests should use local fixtures and avoid live provider or Telegram API
calls. Live checks should be manual or explicitly marked.

## Data and Secrets

- Treat `data/index_dca.sqlite` as stateful MVP data.
- GitHub Actions may commit SQLite state back to the repository.
- Never commit `.env`, tokens, chat IDs, or other private credentials.
- Do not silently mix native index valuation data with ETF proxy fundamentals.
  Preserve `source`, `source_type`, and `metric_schema_version`.

## Development Guidelines

- Follow the feature TODO lists under `docs/<feature>/todo.md`.
- Keep feature plans, tests, and TODOs in the same feature documentation
  directory.
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

