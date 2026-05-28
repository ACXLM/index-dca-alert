# Valuation Signals Plan

## Goal

Convert raw valuation metrics into 5-year percentile ranks, normalize all
metrics so lower means cheaper, calculate a weighted composite percentile, and
map the result to a DCA ratio.

The signal engine is a pure business service. It should accept current
valuation data, already-selected historical valuation rows, and loaded rule
configuration. It should not fetch provider data, query SQLite, write signal
rows, render Telegram messages, or decide daily job orchestration.

Runtime and repository code are responsible for:

- selecting the current valuation row
- reading the configured lookback window from storage
- passing provider failure state into the signal engine when relevant
- persisting the returned signal result through storage repositories

## Metric Direction

| Metric | Raw Meaning | Normalized Cheap Direction |
| --- | --- | --- |
| PE percentile | Lower PE is cheaper | lower percentile is cheaper |
| PB percentile | Lower PB is cheaper | lower percentile is cheaper |
| Price percentile | Lower close price is cheaper | lower percentile is cheaper |
| Dividend yield percentile | Higher yield is cheaper | use `100 - percentile` |
| CAPE percentile | Lower CAPE is cheaper | lower percentile is cheaper |

The configured `price` metric maps to the valuation row's `close` field. If
`close` is missing, zero, or negative, the `price` percentile is `None`.

## Metric Weights

### `cn_broad`

```json
{
  "pe": 0.6,
  "pb": 0.4
}
```

### `hk_broad`

```json
{
  "pe": 0.45,
  "pb": 0.30,
  "dividend_yield_inverse": 0.25
}
```

### `hk_growth_broad`

```json
{
  "pe": 0.45,
  "pb": 0.25,
  "price": 0.30
}
```

### `us_broad`

```json
{
  "pe": 0.55,
  "cape": 0.30,
  "price": 0.15
}
```

### `us_growth_broad`

```json
{
  "pe": 0.55,
  "price": 0.30,
  "pb": 0.15
}
```

## Percentile Calculation

The history input should include the current trade date when the current row has
already been upserted. This matches the planned daily flow:

```text
upsert current valuation -> read lookback history -> calculate signal
```

The signal engine does not choose the 5-year date range. It receives the
historical rows that repository/runtime code selected.

```python
def percentile_rank(values, current, minimum_observations):
    clean = [v for v in values if v is not None and v > 0]
    if current is None or current <= 0 or len(clean) < minimum_observations:
        return None
    count = sum(1 for v in clean if v <= current)
    return round(count / len(clean) * 100, 2)
```

Dividend yield is converted:

```python
dividend_yield_inverse = 100 - dividend_yield_percentile
```

Composite score:

```python
def composite_score(percentiles, weights):
    score = 0.0
    weight_sum = 0.0
    for metric, weight in weights.items():
        value = percentiles.get(metric)
        if value is None:
            continue
        score += value * weight
        weight_sum += weight
    if weight_sum == 0:
        return None
    return round(score / weight_sum, 2)
```

## Signal Quality

| Quality | Meaning | Notify |
| --- | --- | --- |
| `complete` | Primary metrics available and enough history exists | yes |
| `partial` | At least one weighted metric is usable, but some configured metrics are missing or fallback metrics were used | yes, with warning |
| `insufficient_history` | Fewer than 500 valid observations | yes, no DCA amount |
| `fetch_failed` | Provider failed | optional failure alert |

Quality rules:

- `fetch_failed` is produced only when runtime/provider code passes in an
  explicit provider failure state. The signal engine can build the result, but
  it should not catch provider exceptions itself.
- `complete` requires every configured weighted metric for the index category to
  have a percentile.
- `partial` requires at least one configured weighted metric to have a
  percentile and at least one configured weighted metric to be missing, or a
  fallback metric/source to be marked by the caller.
- `insufficient_history` applies when no weighted metric can produce a
  percentile because valid observations are below the configured minimum.
- If no weighted metric can produce a percentile for another reason, return a
  result with no composite score and a non-actionable amount.

Fallback usage should be explicit input to the signal engine, for example
`used_fallback=True` on the current valuation snapshot or signal calculation
call. Runtime/provider code can derive that flag from `source_type` or provider
selection, but the signal engine should not inspect provider internals.

## DCA Ratio

Base amount is fixed at `1000` for MVP.

| Composite Percentile | Zone | Ratio | Suggested Amount |
| --- | --- | --- | --- |
| 0-15 | clearly_undervalued | 2.0 | 2000 |
| 15-30 | mildly_undervalued | 1.2 | 1200 |
| 30-60 | fair | 1.0 | 1000 |
| 60-80 | mildly_overvalued | 0.5 | 500 |
| 80-100 | overvalued | 0.0 | 0 |

Zone boundaries are evaluated as `min <= composite_percentile < max`, except
the final zone includes `composite_percentile == 100`.

`SignalResult.valuation_zone` should use the `zone` value exactly as configured
in `config/rules.yml`. The signal engine should not translate configured zone
labels into hard-coded English enum names.

Suggested amount is:

```python
suggested_amount = base_amount * dca_ratio
```

For `insufficient_history`, `fetch_failed`, or any result without a composite
score, use `dca_ratio = 0` and `suggested_amount = 0` so the result can be
stored in the current non-null schema while remaining non-actionable.

For non-actionable results, use a fixed `valuation_zone` placeholder such as
`不可用`. The signal engine should not render the final Telegram message;
`SignalResult.message` may be an empty string or a short status placeholder, and
the notification renderer is responsible for user-facing language.

Signals are reminders generated from configured rules, not personalized
investment advice.

## Implementation Shape

Add the signal service under `app/services/valuation_signals.py`.

Expected concepts:

- `ValuationSnapshot`
- `MetricPercentiles`
- `SignalResult`
- `percentile_rank`
- `calculate_metric_percentiles`
- `composite_score`
- `select_zone`
- `calculate_signal`
- `fetch_failed_signal`

The service should use standard-library `dataclasses` and plain functions.
