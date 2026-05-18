# Runtime and Scheduling Plan

## Goal

Run the valuation workflow on GitHub Actions after each relevant market close,
skip duplicate fallback runs, and commit updated SQLite state back to the
repository.

The first runtime implementation should focus on the currently implemented data
provider chain: China A-share indices through AKShare CSI. Hong Kong and United
States market-window logic can be implemented and tested, but missing HK/US
providers should not block the first working `daily_run` path.

## Runtime Flow

```text
GitHub Actions schedule
  -> Python daily job
  -> market window check
  -> fetch/update valuation data
  -> update SQLite
  -> calculate 5-year percentiles
  -> generate DCA signal
  -> render Telegram template
  -> send message
  -> commit SQLite state back to repo
```

Detailed runtime flow:

1. Load and validate app configuration.
2. Initialize SQLite and seed configured indices/rules.
3. Determine market, trade date, and run type from CLI arguments or current
   time.
4. If not forced, skip when the current time is outside the market retrieval
   window.
5. If not forced, exit early when any successful `market_runs` row already
   exists for the same market and trade date.
6. Fetch/update valuation data for enabled indices in the selected market.
7. Read current valuation and configured lookback history from storage.
8. Calculate valuation signal for each enabled subscription.
9. Persist generated signals.
10. Dispatch notifications when a subscription and channel configuration are
    available.
11. Record `market_runs.status = success` only after the market work completes.
12. Record `market_runs.status = failed` if the daily run fails at the run
    boundary.

Skipped runs should print a clear stdout message and should not insert
`market_runs` rows. This avoids noisy fallback rows from GitHub Actions.

## Supported Markets

| Market | Index | Code | Category | Primary Metrics |
| --- | --- | --- | --- | --- |
| China A | CSI 300 | `000300` | `cn_broad` | PE, PB |
| China A | CSI 500 | `000905` | `cn_broad` | PE, PB |
| Hong Kong | Hang Seng Index | `HSI` | `hk_broad` | PE, PB, dividend yield |
| Hong Kong | Hang Seng TECH Index | `HSTECH` | `hk_growth_broad` | PE, PB, price percentile |
| United States | S&P 500 | `SPX` | `us_broad` | PE, CAPE fallback, price percentile |
| United States | Nasdaq 100 | `NDX` | `us_growth_broad` | PE, price percentile, PB if available |

## Scheduling

All GitHub Actions cron expressions use UTC. Python decides whether a job should
actually run based on the market timezone and the last successful run.

China A-share and Hong Kong markets both close at 16:00 or earlier local time.
For valuation data, close-after retrieval is more stable than intraday
retrieval.

```yaml
schedule:
  - cron: "30 8 * * 1-5"   # 16:30 Asia/Shanghai, first CN/HK run
  - cron: "30 10 * * 1-5"  # 18:30 Asia/Shanghai, CN/HK fallback
```

US regular trading closes at 16:00 New York time. GitHub Actions does not handle
daylight saving time, so both summer and winter UTC windows are scheduled and
Python filters the actual local time.

```yaml
schedule:
  - cron: "30 20 * * 1-5"  # 16:30 New York during daylight saving time
  - cron: "30 21 * * 1-5"  # 16:30 New York during standard time
  - cron: "30 22 * * 1-5"  # fallback window
```

The fallback run exits if the same market and trade date already succeeded.

Python should use `zoneinfo` for market-local time:

- CN: run Monday-Friday when `Asia/Shanghai` local time is at or after 16:30.
- HK: run Monday-Friday when `Asia/Hong_Kong` local time is at or after 16:30.
- US: run Monday-Friday when `America/New_York` local time is at or after
  16:30, including daylight saving and standard time.
- Weekends do not run.

Exchange holidays are out of scope for the MVP. Provider failures or missing
data should be recorded through data quality events.

The default trade date is the market-local date. `--trade-date` overrides this
for local testing and manual repair runs.

## CLI

The daily job command is:

```bash
uv run python -m app.jobs.daily_run
```

Options:

- `--market CN|HK|US`: optional market override
- `--trade-date YYYY-MM-DD`: optional trade date override
- `--run-type primary|fallback|manual`: defaults to inferred schedule/manual
- `--force`: skip market-window checks and successful market-date early exit
- `--db-path PATH`: defaults to `data/index_dca.sqlite`
- `--dry-run`: execute planning and rendering paths without sending Telegram or
  committing durable notification attempts

Manual local testing should use `--force` so developers can run the flow outside
market windows.

## Idempotency

Runtime uses two market-run concepts:

- exact run identity: `(market, trade_date, run_type)`
- successful market date: any `success` row for `(market, trade_date)`

Fallback early exit uses the successful market-date check. If the primary run
succeeded, a later fallback exits even though its `run_type` differs.

`--force` skips the successful market-date early exit for manual repair runs.

Valuation writes, signal writes, and notification attempts should use the
storage repositories' idempotent or append-only semantics:

- valuation rows upsert by `(index_id, trade_date, source)`
- signal rows upsert by `(user_subscription_id, trade_date)`
- notification rows record each send attempt

## Subscriptions and Notifications

Runtime should bootstrap a default subscription per enabled index so signal
identity is stable even during local runs without Telegram configuration.

For the first MVP runtime:

- if `TG_CHAT_ID` is available, create or reuse a default Telegram subscription
  for each enabled index in the selected market
- if `TG_CHAT_ID` is missing, create or reuse the same default subscription
  identity with `notify_target = "local-disabled"` so signals can still be
  persisted
- default `user_id = "default"`
- default `notify_channel = "telegram"`
- default `base_amount = config/rules.yml base_amount`
- if `TG_CHAT_ID` is missing, generate valuations/signals but skip notification
  dispatch

Runtime is responsible for mapping signal engine output into storage
`SignalInput`, including all percentile fields and the message placeholder.

Runtime is also responsible for building `NotificationContext` from:

- index metadata
- current valuation row
- subscription base amount and target
- generated signal result

Notifications should still be sent through the notification dispatcher rather
than directly through Telegram-specific code.

## Failure Handling

Provider or index-level failures should be recorded in `data_quality_events`
and should not prevent other indices in the market from running.

If every index in the selected market fails to produce usable valuation data,
the market run should be marked `failed`.

Unexpected exceptions at the daily-run boundary should record
`market_runs.status = failed` with an error message, then return a non-zero exit
code.

Successful completion records `market_runs.status = success`.

## GitHub Actions

The workflow runs Python 3.11, installs dependencies, runs the daily job, and
commits `data/index_dca.sqlite` when it changed.

The project uses `uv` for dependency management. The workflow should use
`uv sync --frozen` and `uv run python -m app.jobs.daily_run`.

The workflow should not use `requirements.txt`.

The SQLite commit step should succeed when there are no changes:

```bash
git add data/index_dca.sqlite
git diff --cached --quiet || git commit -m "chore: update valuation data"
```
