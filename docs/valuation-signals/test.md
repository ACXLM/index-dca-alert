# Valuation Signals Tests

## Unit Tests

- Percentile calculation ignores null, zero, and negative values.
- Percentile calculation returns `None` below the observation threshold.
- Percentile calculation includes the current trade date when it is present in
  the provided history values.
- Percentile calculation returns deterministic rounded values.
- Dividend yield percentile is reversed into cheap-direction score.
- The configured `price` metric uses the valuation `close` value.
- Composite score renormalizes weights when optional metrics are missing.
- Composite score returns `None` when all weighted metrics are missing.
- DCA ratio boundaries are deterministic at 0, 15, 30, 60, 80, and 100.
- Zone selection uses `min <= score < max`, with the final zone including 100.
- Suggested amount equals `base_amount * dca_ratio`.
- Missing composite scores produce `dca_ratio = 0` and `suggested_amount = 0`.
- Signal quality is `complete` when every configured weighted metric has a
  percentile.
- Signal quality is `insufficient_history` when observations are below the
  minimum threshold.
- Signal quality is `partial` when at least one configured metric is usable and
  at least one configured metric is missing.
- Signal quality is `partial` when explicit fallback usage is marked.
- Signal quality is `fetch_failed` only from an explicit provider failure state.
- `valuation_zone` uses the configured zone label exactly.
- Non-actionable results use `valuation_zone = "不可用"`, `dca_ratio = 0`, and
  `suggested_amount = 0`.

## Integration Tests

- Signal generation reads metric weights and zone rules from loaded
  `RulesConfig`.
- Signal generation accepts current valuation and history rows without querying
  storage directly.
- Runtime/storage integration later writes one signal per subscription and trade
  date using the storage repository.
- Runtime/storage integration later selects only rows inside the configured
  5-year lookback window before calling the signal engine.
