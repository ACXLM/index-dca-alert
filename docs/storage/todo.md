# Storage and Persistence TODO

- [x] Implement SQLite initialization from `app/schema.sql`.
- [x] Add a SQLite connection helper that enables foreign keys per connection.
- [x] Seed configured indices from `config/indices.yml`.
- [x] Seed DCA rules from `config/rules.yml`.
- [x] Preserve existing row IDs when reseeding indices and DCA rules.
- [x] Define repository interfaces around core read/write operations.
- [x] Keep repository writes inside explicit transaction boundaries.
- [x] Implement idempotent valuation upserts.
- [x] Implement market run tracking.
- [x] Implement successful market-date lookup across run types for fallback
  idempotency.
- [x] Define user subscription repository operations; leave default Telegram
  subscription bootstrap to runtime or notifications.
- [x] Cover repository SQL safety with parameterized-query tests.
- [x] Add PostgreSQL migration path after the MVP if needed.
