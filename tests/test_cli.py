from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from keel.cli import app
from tests.conftest import REFERENCE

runner = CliRunner()


def test_verify_reference_exits_zero() -> None:
    res = runner.invoke(app, ["verify", str(REFERENCE)])
    assert res.exit_code == 0, res.output
    assert "GB200-1SU-POC" in res.output


def test_verify_strict_fails_on_unrun() -> None:
    assert runner.invoke(app, ["verify", "--strict", str(REFERENCE)]).exit_code == 1


def test_verify_markdown_for_pr_comments() -> None:
    res = runner.invoke(app, ["verify", "-f", "md", str(REFERENCE)])
    assert res.output.startswith("### Keel verify")


def test_verify_exits_one_on_fail(tmp_path: Path) -> None:
    text = REFERENCE.read_text(encoding="utf-8").replace(
        "ups-bypass-A:\n    overrides: {UPS-A: bypass, SW-BYP-A: closed}",
        "ups-bypass-A:\n    overrides: {UPS-A: bypass}",  # bypass switch left open -> side A dead
    )
    broken = tmp_path / "netlist.yaml"
    broken.write_text(text, encoding="utf-8")
    res = runner.invoke(app, ["verify", str(broken)])
    assert res.exit_code == 1
    assert "A-01@ups-bypass-A" in res.output


def test_netlist_error_exits_two(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"keel": "0.1", "nodes": [{"id": "X"}]}), encoding="utf-8")
    res = runner.invoke(app, ["verify", str(bad)])
    assert res.exit_code == 2
