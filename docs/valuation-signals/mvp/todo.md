# Valuation Signals TODO

- [x] Add `app.services.valuation_signals` as a pure business service.
- [x] Define signal input and result dataclasses.
- [x] Implement percentile calculation with the configured minimum observation
  threshold.
- [x] Treat provided history as the complete calculation sample, including the
  current trade date when present.
- [x] Implement dividend-yield inverse percentile logic.
- [x] Map configured `price` metric to the valuation `close` field.
- [x] Implement composite scoring with weight renormalization for missing
  optional metrics.
- [x] Implement DCA ratio selection from configured zone rules.
- [x] Preserve configured zone labels in signal results.
- [x] Implement suggested amount calculation from base amount and DCA ratio.
- [x] Emit `complete`, `partial`, `insufficient_history`, and `fetch_failed`
  signal quality states.
- [x] Accept explicit fallback usage input for partial signal quality.
- [x] Use non-actionable placeholders for unavailable signal results.
- [x] Keep provider fetching, storage reads/writes, notification rendering, and
  runtime orchestration outside the signal engine.
- [x] Add valuation signal unit tests for percentile, composite score, zone
  boundaries, suggested amount, and signal quality.
