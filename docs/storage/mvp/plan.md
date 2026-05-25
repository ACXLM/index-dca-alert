# Storage and Persistence Plan

## Goal

Persist index metadata, valuation history, generated signals, notification
attempts, market runs, and data quality events in SQLite.

SQLite is the MVP database. `data/index_dca.sqlite` is stateful application data
and may be committed back to the repository by GitHub Actions.

The executable schema lives in `app/schema.sql`.

## UUID Strategy

Use UUIDv4 text primary keys for all application tables:

```text
id TEXT PRIMARY KEY
```

Reasons:

- Identity generation stays consistent across local SQLite, GitHub Actions,
  imports, exports, and future Telegram-created entities.
- UUIDs make conflict resolution and a later PostgreSQL migration simpler.
- The project has tiny data volume, so UUID overhead is acceptable.

## Core Tables

Core uniqueness constraints:

- `indices.code` is unique.
- `index_valuations(index_id, trade_date, source)` is unique.
- `valuation_signals(user_subscription_id, trade_date)` is unique.
- `market_runs(market, trade_date, run_type)` is unique.

Store dates and timestamps as ISO-8601 text:

```text
trade_date: YYYY-MM-DD
created_at: YYYY-MM-DDTHH:MM:SSZ
```

This keeps SQLite simple and makes exported rows readable.

## Persistence Rules

Scheduled jobs must be safe to rerun. Database writes should use natural
uniqueness constraints and idempotent upserts instead of assuming a job runs only
once.

Persistence logic should sit behind repository abstractions. The domain and
application services should not contain ad hoc SQL.

Every SQLite connection used by the application must enable foreign key
enforcement after opening the connection:

```sql
PRAGMA foreign_keys = ON;
```

This is a per-connection setting in SQLite. Keeping it in `app/schema.sql` is
useful for schema execution, but repository connection helpers must also enable
it.

Repository operations that write related rows should run in transactions. Seed
operations and idempotent upserts should either complete fully or leave the
database unchanged.

Seed operations should preserve stable IDs for existing rows:

- seed `indices` by `indices.code`
- seed `dca_rules` by `dca_rules.category`

When a seed row already exists, update mutable fields and `updated_at` while
preserving the existing `id`. This avoids breaking foreign keys held by
valuations, subscriptions, signals, or notifications.

Market run tracking needs two related checks:

- exact run identity: `(market, trade_date, run_type)`
- successful market date: any successful run for `(market, trade_date)`

The fallback scheduler should use the successful market-date check so a later
fallback exits after an earlier run for the same market and trade date
succeeded, even when the fallback has a different `run_type`.

The MVP subscription bootstrap strategy is still pending. Storage should expose
repository operations for `user_subscriptions`, but the decision about creating
or updating a default Telegram subscription from environment variables belongs
to the runtime or notifications feature.

Common read paths should stay simple for the MVP:

- look up indices by `code`
- read valuation history by `index_id` and trade date range
- check market run success by `market` and `trade_date`

The existing natural uniqueness constraints support these paths for MVP data
volume. Additional indexes can be added later if query plans show a real need.

## SQL Safety

Use Python's standard-library `sqlite3` module with parameterized queries for
all runtime values.

Do not build SQL values with f-strings, `%` formatting, `.format()`, or string
concatenation. Repository methods should use `?` placeholders and pass values as
a separate parameter tuple or mapping.

Dynamic SQL identifiers such as table names, column names, and sort fields must
not come from provider data, YAML values, environment variables, or CLI
arguments. If an identifier must vary, select it from an explicit in-code
allowlist.

Application services and jobs should call repository methods instead of
constructing ad hoc SQL directly.

## PostgreSQL Migration Path

PostgreSQL is out of scope for the MVP, but storage choices should keep a later
migration straightforward:

- keep UUIDv4 text IDs at the application boundary
- keep dates and timestamps as explicit ISO-8601 values in domain objects
- keep SQL behind repository methods
- keep seed and upsert behavior keyed by natural uniqueness constraints
- avoid relying on SQLite-specific behavior outside the repository layer

If PostgreSQL is added after the MVP, introduce migration scripts and a
PostgreSQL repository implementation behind the same repository method surface
instead of changing provider, signal, notification, or runtime services.
