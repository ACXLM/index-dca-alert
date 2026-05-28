from __future__ import annotations

import pytest

from app.jobs.feishu_smoke import main as feishu_smoke_main


def test_feishu_smoke_dry_run_renders_message(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = feishu_smoke_main(["--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "指数定投提醒" in captured.out
    assert "指数：沪深300" in captured.out


def test_feishu_smoke_dry_run_renders_feishu_format(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = feishu_smoke_main(["--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "综合估值百分位" in captured.out
    assert "建议金额" in captured.out
