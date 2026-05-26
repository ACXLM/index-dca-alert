from __future__ import annotations

import argparse
from typing import Sequence

from app.services.credential import load_fernet_from_env, decrypt_credential
from app.services.feishu_channel import FeishuChannel, FeishuConfig, FeishuRenderer
from app.services.notifications import NotificationContext


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    context = _fixture_context()

    if args.dry_run:
        print(FeishuRenderer().render(context))
        return 0

    fernet = load_fernet_from_env()
    cred = decrypt_credential(fernet, args.credential_enc)
    config = FeishuConfig(webhook_token=cred["webhook_token"])
    channel = FeishuChannel(config)
    result = channel.send(context)
    print(f"{result.channel}: {result.status}")
    if result.error_message:
        print(f"error: {result.error_message}")
    return 0 if result.status == "sent" else 1


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render or send a Feishu smoke notification.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--send", action="store_true")
    parser.add_argument("--credential-enc", default=None, help="Encrypted credential blob from DB")
    return parser.parse_args(argv)


def _fixture_context() -> NotificationContext:
    return NotificationContext(
        signal_id="feishu-smoke",
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
