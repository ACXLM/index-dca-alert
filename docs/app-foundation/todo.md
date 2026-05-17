# App Foundation TODO

- [x] Add `pyproject.toml` for `uv`-managed project metadata and test tooling.
- [x] Create the shallow Python package structure under `app/`.
- [x] Implement typed config objects in `app.config`.
- [x] Implement loading for `config/indices.yml` and `config/rules.yml`.
- [x] Keep explicit `enabled` fields in MVP index configuration.
- [x] Default missing index `enabled` fields to enabled.
- [x] Validate enabled index categories against configured metric weights.
- [x] Validate base amount, lookback years, and minimum observation settings.
- [x] Validate metric weights.
- [x] Validate DCA zone boundaries, coverage, and ratios.
- [x] Add foundation unit tests for config loading and validation.
- [x] Document the local foundation test command once packaging is in place.
