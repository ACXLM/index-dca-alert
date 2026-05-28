# Documentation

Project documentation is organized by business feature. Each feature owns its
plan, test design, and TODO list under a version directory so completed release
baselines stay separate from later iteration plans.

This layout keeps implementation context local to the feature being changed and
avoids splitting one feature across global `plans/`, `tests/`, and `todos/`
directories.

## Feature Directories

Each feature directory should use this structure:

```text
docs/<feature>/
  README.md       Feature documentation map and current status.
  <version>/
    plan.md      Business goal, design, data flow, rules, and implementation notes.
    test.md      Unit, integration, fixture, and manual verification requirements.
    todo.md      Feature-scoped implementation checklist.
```

## Current Features

- `app-foundation/`: Python package structure, project metadata, configuration
  loading, and configuration validation.
- `runtime/`: scheduling, GitHub Actions, CLI jobs, and idempotent market runs.
- `storage/`: SQLite schema, UUID strategy, repository boundaries, and
  persistence rules.
- `data-providers/`: provider hierarchy, backfill, source assumptions, and data
  quality events.
- `valuation-signals/`: percentile calculation, composite scoring, signal
  quality, and DCA ratio rules.
- `notifications/`: versioned Telegram rendering, sending, secrets, and
  notification status tracking documentation.
- `mvp-release/`: cross-feature release checklist and manual smoke test.

## Documentation Rules

- Put new documentation under the feature directory that owns the behavior.
- Keep feature plans, tests, and TODOs together under a version subdirectory,
  for example `mvp/` or `v2/`.
- Add a new feature directory only when there is a real business or workflow
  boundary.
- Do not create global type-based folders such as `tests/`, `todos/`, or
  `plans/` unless a future need clearly spans all features.
