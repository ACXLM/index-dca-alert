# Storage and Persistence Tests

## Integration Tests

- SQLite initializes successfully from `app/schema.sql`.
- Foreign key enforcement is enabled.
- Foreign key enforcement is enabled for every application connection, not only
  during schema initialization.
- A foreign key violation fails in tests.
- Configured indices are seeded idempotently from `config/indices.yml`.
- Reseeding configured indices updates mutable fields but preserves existing
  row IDs.
- DCA rules are seeded idempotently from `config/rules.yml`.
- Reseeding DCA rules updates mutable fields but preserves existing row IDs.
- Backfill inserts historical rows idempotently.
- Daily update upserts the same `index_id + trade_date + source` row.
- Signal generation writes only one signal per subscription and trade date.
- Market run tracking prevents duplicate successful runs for the same market,
  trade date, and run type.
- Market run tracking reports a successful market date across run types so a
  fallback can exit after an earlier successful run.
- Repository writes are transactional: a failing multi-row write does not leave
  partial rows behind.
- Repository methods use parameterized queries; SQL-like characters in values
  are stored or queried as data and do not alter SQL behavior.

## Migration Checks

- All application tables use `id TEXT PRIMARY KEY`.
- Dates and timestamps use ISO-8601 text formats.
- Natural uniqueness constraints match the idempotency requirements documented
  in the plan.
