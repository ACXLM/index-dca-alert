# Index DCA Alert - Agent Guide

## 1. Project Overview

### Project Goal

Build a minimal index valuation percentile and DCA reminder system that runs on
GitHub Actions, stores valuation history in SQLite, and sends Telegram and Feishu Bot
notifications.

### Core Business Logic

The MVP data flow is:

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

Scheduled jobs must be idempotent. If a market and trade date were already
processed successfully, the next fallback run exits early.

## 2. Tech Stack Specifications

### Language and Version

- Python 3.11+.
- Manage the project with `uv`.
- Prefer `pyproject.toml` and `uv.lock` for dependency and tool configuration.
- Do not add new dependencies to `requirements.txt`; migrate away from
  `requirements.txt` when project packaging is implemented.
- Use the standard library where practical, especially `sqlite3`, `uuid`,
  `datetime`, `zoneinfo`, `json`, and `pathlib`.

### Frameworks and Key Libraries

Runtime dependencies should stay intentionally small:

- `akshare` for China index valuation data.
- `cryptography` for secure notification credential encryption.
- `pandas` for provider response normalization where useful.
- `pyyaml` for configuration files.
- `requests` for Telegram/Feishu and simple HTTP adapters.
- `yfinance` for Yahoo Finance price/fallback data.

Do not add a web framework, ORM, task queue, or heavy application framework for
the MVP unless explicitly requested.

### Infrastructure

- SQLite is the application database.
- `data/index_dca.sqlite` is stateful MVP data and may be committed by GitHub
  Actions.
- GitHub Actions is the scheduler and runtime.
- Telegram and Feishu Bots are the notification channels.
- Secrets and the master credential key (`APP_CREDENTIAL_KEY`) must live only in GitHub Actions secrets or local `.env`; never commit
  tokens or chat IDs.

## 3. Project Structure

### Directory Map

```text
app/
  schema.sql              SQLite DDL. Keep executable schema here.
  jobs/                   CLI entry points such as daily_run and backfill.
  providers/              Data-source adapters by provider/market.
  services/               Business logic: scoring, signals, notifications.
  repositories/           SQLite read/write helpers if needed.
  config.py               Config loading and validation.

config/
  indices.yml             Supported index metadata and provider symbols.
  rules.yml               Lookback, metric weights, and DCA zone rules.

data/
  index_dca.sqlite        Stateful local/GitHub Actions SQLite database.

docs/
  README.md               Documentation map.
  runtime/                Scheduling, GitHub Actions, and market runs.
    plan.md
    test.md
    todo.md
  storage/                SQLite schema, UUID strategy, and persistence rules.
    plan.md
    test.md
    todo.md
  data-providers/         Provider hierarchy, backfill, and data quality.
    plan.md
    test.md
    todo.md
  valuation-signals/      Percentiles, scoring, signal quality, DCA rules.
    plan.md
    test.md
    todo.md
  notifications/          Telegram rendering, sending, and status tracking.
    plan.md
    test.md
    todo.md
  mvp-release/            Cross-feature release checklist and smoke test.
    plan.md
    test.md
    todo.md

templates/
  telegram_signal.md      MVP Telegram message template.
```

Create new files only inside the directory that owns the behavior. Keep the MVP
flat and readable; avoid introducing nested package layers before there is real
complexity.

### Naming Conventions

- Python modules and functions use `snake_case`.
- YAML keys use `snake_case`.
- SQLite tables and columns use `snake_case`.
- Job modules should use action-oriented names, for example
  `app.jobs.backfill` and `app.jobs.daily_run`.
- Provider modules should name the source or market clearly, for example
  `akshare_csindex.py`, `hk_index_adapter.py`, and `us_index_adapter.py`.

## 4. Coding Standards

### Error Handling

- Do not use `panic`-style exits for normal failures.
- Raise exceptions with enough context at low levels; catch them at job
  boundaries to record run status and notification failures.
- Provider failures must not silently produce valid-looking valuation rows.
  Record failures in `data_quality_events` when relevant.
- Never mix valuation metrics from different source meanings without recording
  `source`, `source_type`, and `metric_schema_version`.

### Design Patterns

- Follow a lightweight DDD style driven by business concepts, not directory
  templates. Identify domain entities, value objects, domain services,
  repositories, provider adapters, and application jobs only where they map to
  real behavior in this system.
- Do not use directory-driven DDD. Model boundaries must come from real business
  concepts and workflows, not from creating layers for their own sake.
- Start from domain concepts such as Index, Valuation, Percentile, DCA Signal,
  Market Run, Provider Coverage, and Notification. Add modules and interfaces
  only when they clarify one of these concepts or an extension boundary.
- Prefer explicit interfaces or protocols at extension boundaries, especially
  for providers, repositories, notification channels, and scoring services.
- Use abstractions to make provider replacement, storage migration, and
  notification expansion understandable. Avoid abstraction only for very simple
  linear logic where functions are clearer.
- Keep provider adapters separate from scoring logic and domain rules.
- Keep persistence rules behind repository abstractions so idempotent upsert
  behavior is reused consistently.
- Use UUIDv4 text primary keys for all application tables. This keeps identity
  generation consistent across local SQLite, GitHub Actions, imports, exports,
  future Telegram-created entities, and a later PostgreSQL migration.
- Use natural uniqueness constraints such as
  `(index_id, trade_date, source)` and `(market, trade_date, run_type)` to make
  scheduled jobs safe to rerun.

### Comments and Documentation

- Document data-source assumptions before changing provider behavior.
- Add comments only where the code is not self-explanatory, especially around
  provider field interpretation, percentile thresholds, and market-time logic.
- Keep user-facing notification language in templates, not hard-coded across
  services.

## 5. Workflow and Constraints

### Testing Requirements

- New scoring, percentile, market-window, and idempotency behavior must include
  tests.
- Keep tests documented in the relevant `docs/<feature>/test.md` file next to
  that feature's `plan.md` and `todo.md`.
- Use `docs/mvp-release/test.md` for cross-feature release checks.
- Prefer deterministic unit tests with local fixtures. Avoid live provider calls
  in normal tests.
- Live provider or notification (Telegram/Feishu) checks should be manual or explicitly marked so they
  do not run by default in CI.

### Blacklist

- No web UI for the MVP.
- No SMS channel for the MVP.
- No paid data source unless explicitly added later.
- No third-party ORM unless explicitly approved.
- No background worker, Redis, Docker, or Kubernetes requirement for the MVP.
- No committed secrets, tokens, chat IDs, or private `.env` files.
- No silent replacement of native index valuation data with ETF proxy data.

### Git Commit Guidance

After completing a functional TODO workstream or a meaningful standalone task,
create a commit so the change is easy to review. Do not wait for unrelated TODO
items before committing completed work.

Use Conventional Commits with a clear explanation of the functional change:

```text
feat: add daily valuation job
fix: make market run idempotent
docs: group MVP tasks by feature
test: cover percentile boundary rules
chore: update GitHub Actions schedule
```

Commit messages should describe the user-visible, domain, or operational change,
not just the touched file.

**Commit granularity rules** (agreed on 2026-05-26):

- One commit per `todo.md` workstream item. Do not batch multiple items into a
  single commit. This makes each step independently reviewable and revertable.
- For TDD workstreams, combine tests and implementation in the same commit. A
  failing test with no implementation has no standalone value to a reviewer.
- When a schema or API change breaks existing tests in unrelated files, commit
  those test fixes as a separate `fix:` or `test:` commit immediately after the
  commit that introduced the breaking change. Label it clearly, for example:
  `test: update storage and runtime tests for v2 schema`.
- Never include documentation-only changes (`docs:`) in the same commit as code
  changes. Keep them separate so `git log --oneline` stays scannable.
