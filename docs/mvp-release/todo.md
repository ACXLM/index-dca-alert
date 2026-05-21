# MVP Release TODO

## Documentation

- [ ] Add local MVP run instructions to `README.md`.
- [ ] Link `docs/mvp-release/test.md` from the documentation map.
- [ ] Document that the release gate is CN only: `000300` and `000905`.
- [ ] Document that HK/US indices are configured roadmap items, not MVP
  release gates.

## Automated Verification

- [ ] Run the full test suite with `UV_CACHE_DIR=/tmp/uv-cache uv run pytest
  tests`.
- [ ] Confirm provider tests cover rejection of recent-only CN history.
- [ ] Confirm runtime tests cover `.env` loading for Telegram.
- [ ] Confirm backfill tests cover cached windows and missing-tail incremental
  fetch windows.

## Local Data Smoke Test

- [ ] Create a throwaway SQLite database under `data/`.
- [ ] Run CN five-year backfill.
- [ ] Verify `000300` and `000905` history row counts and date ranges.
- [ ] Verify CN valuation rows use `source = "akshare_legulegu_index"`.
- [ ] Verify latest PE and PB values are positive.
- [ ] Manually calculate PE percentile for at least `000300`.
- [ ] Run `daily_run --market CN --run-type manual --force`.
- [ ] Verify current signals for both CN indices.
- [ ] Verify signal quality and suggested amount.

## Notification Smoke Test

- [ ] Verify no notification rows are created when Telegram config is absent or
  `--dry-run` is used.
- [ ] Add local `.env` with `TG_BOT_TOKEN` and `TG_CHAT_ID`.
- [ ] Run `daily_run --market CN --run-type manual --force`.
- [ ] Verify Telegram receives the message.
- [ ] Verify `notifications.status = sent` for successful sends.
- [ ] Verify failed sends store sanitized `error_message`.

## Idempotency And Incremental Behavior

- [ ] Re-run the same CN backfill and verify cached indices are skipped.
- [ ] Run backfill with a missing tail and verify only the missing date window
  is requested.
- [ ] Run backfill with `--refresh` and verify it bypasses cache intentionally.
- [ ] Run a fallback daily job after a successful same-market same-date run and
  verify it skips.
- [ ] Run a forced manual daily job and verify notification attempts are
  append-only.

## GitHub Actions

- [ ] Verify workflow uses `uv sync --frozen`.
- [ ] Verify workflow runs `uv run python -m app.jobs.daily_run`.
- [ ] Verify Telegram values come only from GitHub Actions secrets.
- [ ] Verify SQLite commit step is no-op safe.
- [ ] Manually trigger the workflow after secrets are configured.

## Release Commit

- [ ] Ensure no `.env`, tokens, chat IDs, or unrelated local data files are
  staged.
- [ ] Ensure local throwaway SQLite files are not committed unless explicitly
  intended.
- [ ] Commit MVP release documentation and any release-readiness changes with a
  Conventional Commit message.
