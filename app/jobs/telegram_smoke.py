from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from app.repositories.sqlite import NotificationRepository, connect
from app.services.notifications import (
    NotificationContext,
    NotificationDispatcher,
    TelegramChannel,
    TelegramConfig,
    TelegramRenderer,
)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    context = _fixture_context()

    if args.dry_run:
        print(TelegramRenderer().render(context))
        return 0

    config = TelegramConfig.from_env()
    repository = None
    connection = None
    try:
        if args.db_path is not None:
            connection = connect(Path(args.db_path))
            repository = NotificationRepository(connection)
        dispatcher = NotificationDispatcher(
            [TelegramChannel(config)],
            repository=repository,
        )
        results = dispatcher.dispatch(context)
        for result in results:
            print(f"{result.channel}: {result.status}")
        return 0 if all(result.status == "sent" for result in results) else 1
    finally:
        if connection is not None:
            connection.close()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render or send a Telegram smoke notification.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--send", action="store_true")
    parser.add_argument("--db-path", default=None)
    return parser.parse_args(argv)


def _fixture_context() -> NotificationContext:
    return NotificationContext(
        signal_id="telegram-smoke",
        index_name="沪深300",
        trade_date="2026-05-18",
        market="CN",
        category="cn_broad",
        pe=12.5,
        pe_percentile=25.0,
        pb=1.3,
        pb_percentile=30.0,
        cape_percentile=None,
        dividend_yield_percentile=None,
        price_percentile=None,
        composite_percentile=27.0,
        signal_quality="partial",
        valuation_zone="合理偏低",
        base_amount=1000,
        dca_ratio=1.2,
        suggested_amount=1200,
    )


if __name__ == "__main__":
    raise SystemExit(main())
