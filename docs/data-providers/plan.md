# Data Providers Plan

## Goal

Fetch valuation and price data for the supported global broad-market indices
without paid data sources in the MVP.

The MVP intentionally avoids Tushare and starts with free data sources only.

| Market | Primary Source | Use | Notes |
| --- | --- | --- | --- |
| China A | AKShare CSI valuation | PE, PB, dividend yield | CSI valuation endpoint is the cleanest free MVP source for China indices. |
| Hong Kong | AKShare/Yahoo Finance derived data | price history, current fundamentals where available | Historical PE/PB may require provider-specific adapters. |
| United States | Shiller/DataHub/Yahoo-derived adapters | S&P 500 PE/CAPE, price history, ETF proxy fundamentals | Historical daily index PE is not consistently free. Use documented fallback hierarchy. |

Provider adapters must preserve source meaning. Do not silently merge native
index valuation data with ETF proxy fundamentals.

## Implementation Scope

Implement the provider workstream in narrow slices.

The first implementation slice should include:

- provider interfaces and canonical valuation objects
- AKShare CSI provider for CSI 300 and CSI 500
- `app.jobs.backfill`
- fixture-based tests for provider normalization and backfill idempotency

Hong Kong and United States adapters stay in the documented roadmap, but they
should not block the first working China A-share provider/backfill chain.

## Provider Boundary

Provider adapters fetch and normalize source data. They should not write
SQLite, calculate valuation signals, send notifications, or decide runtime
scheduling.

Expected concepts:

- `ProviderValuation`
- `ProviderError`
- `HistoricalValuationProvider`
- `fetch_history(index, start_date, end_date)`

The provider output should map to storage's canonical valuation fields:

- `trade_date`
- `pe`
- `pb`
- `cape`
- `dividend_yield`
- `close`
- `source`
- `source_type`
- `metric_schema_version`
- `raw_json`

Provider normalization rules:

- `trade_date` is required.
- At least one core valuation metric or `close` must be a positive value.
- Optional missing fields are represented as `None`, not `0`.
- Rows with all metrics missing or invalid are skipped and recorded as data
  quality events by the caller.
- Provider failures raise `ProviderError` with enough context and must not
  produce valid-looking rows.

## Source Hierarchy

### CSI 300 and CSI 500

Use AKShare CSI valuation:

```python
ak.stock_zh_index_value_csindex(symbol="000300")
ak.stock_zh_index_value_csindex(symbol="000905")
```

Persist PE, PB, dividend yield, close when available, and always store
`metric_schema_version`.

AKShare CSI native valuation rows should use:

- `source = "akshare_csindex"`
- `source_type = "native_index"`
- `metric_schema_version = "csindex_v1"`

### Hang Seng Index and Hang Seng TECH

Target data:

- HSI: PE, PB, dividend yield, close.
- HSTECH: PE if available, PB if available, close.

Provider order:

1. AKShare Hong Kong index/fundamental adapter if fields are available.
2. Yahoo Finance price history for `^HSI` and Hang Seng TECH ticker/proxy.
3. ETF proxy fallback for current fundamentals only, recorded separately as
   `source_type = etf_proxy`.

If only price history is available for HSTECH, calculate a price percentile and
mark signal quality as `partial`.

### S&P 500 and Nasdaq 100

Target data:

- SPX: PE, CAPE fallback, close.
- NDX: PE if available, close; PB optional.

Provider order:

1. S&P 500 historical PE/CAPE dataset adapter for SPX.
2. Yahoo Finance price history for `^GSPC` and `^NDX`.
3. ETF proxy current fundamentals for SPY/QQQ if index-level current PE is not
   available.

ETF proxy fundamentals are not identical to index fundamentals. Store
`source_type = etf_proxy` when used.

## Data Quality Events

Use fixed event types so provider and runtime behavior is easy to test:

- `provider_failure`
- `coverage_gap`
- `missing_required_field`
- `empty_response`
- `invalid_row`
- `normalization_error`

## Historical Backfill

The daily job needs a 5-year lookback window. Initial setup runs:

```text
uv run python -m app.jobs.backfill
```

CLI options:

- `--years`: optional, defaults to `config/rules.yml` `lookback_years`
- `--market CN|HK|US`: optional market filter
- `--index-code CODE`: optional single-index filter
- `--db-path PATH`: optional database path for local runs and tests

Backfill behavior:

1. Load and validate app configuration.
2. Initialize SQLite from `app/schema.sql`.
3. Seed configured indices and DCA rules.
4. Read enabled indices from `config/indices.yml`, applying CLI filters.
5. Resolve the provider from each index's `primary_provider`.
6. For each index, call the provider's historical endpoint where available.
7. Normalize fields into canonical valuation rows.
8. Upsert rows into `index_valuations`.
9. Record source coverage gaps and provider failures in
   `data_quality_events`.

If a provider only supplies recent valuation data, store all available history
and mark the remaining window as missing. The signal engine must require a
minimum observation count before generating strong signals.

Backfill should not calculate signals, send Telegram notifications, or apply
market-window scheduling logic. Those responsibilities belong to later runtime
and notification workstreams.

Each index backfill should run with a clear transaction boundary. A provider
failure for one index should be recorded without corrupting successfully
processed indices.
