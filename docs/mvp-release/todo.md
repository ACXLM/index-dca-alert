# MVP Release TODO

## Documentation

- [x] Add local MVP run instructions to `README.md`.
- [x] Link `docs/mvp-release/test.md` from the documentation map.
- [x] Document that the release gate is CN only: `000300` and `000905`.
- [x] Document that HK/US indices are configured roadmap items, not MVP
  release gates.

## Automated Verification

- [x] Run the full test suite with `UV_CACHE_DIR=/tmp/uv-cache uv run pytest
  tests`.
- [x] Confirm provider tests cover rejection of recent-only CN history.
- [x] Confirm runtime tests cover `.env` loading for Telegram.
- [x] Confirm backfill tests cover cached windows and missing-tail incremental
  fetch windows.

## Local Data Smoke Test

- [x] Create a throwaway SQLite database under `data/`.
- [x] Run CN five-year backfill.
- [x] Verify `000300` and `000905` history row counts and date ranges.
- [x] Verify CN valuation rows use `source = "akshare_legulegu_index"`.
- [x] Verify latest PE and PB values are positive.
- [x] Manually calculate PE percentile for at least `000300`.
- [x] Run `daily_run --market CN --run-type manual --force`.
- [x] Verify current signals for both CN indices.
- [x] Verify signal quality and suggested amount.

## Notification Smoke Test

- [x] Verify no notification rows are created when Telegram config is absent or
  `--dry-run` is used.
- [x] Add local `.env` with `TG_BOT_TOKEN` and `TG_CHAT_ID`.
- [x] Run `daily_run --market CN --run-type manual --force`.
- [x] Verify Telegram accepts the message and runtime reports sent attempts.
- [x] Verify `notifications.status = sent` for successful sends.
- [x] Verify failed sends store sanitized `error_message`.

## Idempotency And Incremental Behavior

- [x] Re-run the same CN backfill and verify cached indices are skipped.
- [x] Run backfill with a missing tail and verify only the missing date window
  is requested.
- [x] Run backfill with `--refresh` and verify it bypasses cache intentionally.
- [x] Run a fallback daily job after a successful same-market same-date run and
  verify it skips.
- [x] Run a forced manual daily job and verify notification attempts are
  append-only.

## GitHub Actions

- [x] Verify workflow uses `uv sync --frozen`.
- [x] Verify workflow runs `uv run python -m app.jobs.daily_run`.
- [x] Verify Telegram values come only from GitHub Actions secrets.
- [x] Verify SQLite commit step is no-op safe.
- [ ] Manually trigger the workflow after secrets are configured.

## Release Commit

- [x] Ensure no `.env`, tokens, chat IDs, or unrelated local data files are
  staged.
- [x] Ensure local throwaway SQLite files are not committed unless explicitly
  intended.
- [x] Commit MVP release documentation and any release-readiness changes with a
  Conventional Commit message.
