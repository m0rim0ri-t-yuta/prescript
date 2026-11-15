from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from prescript.cli import app
from tests.conftest import REFERENCE

runner = CliRunner()


def test_verify_reference_exits_zero() -> None:
    res = runner.invoke(app, ["verify", str(REFERENCE)])
    assert res.exit_code == 0, res.output
    assert "GB200-1SU-DLC-POC" in res.output


def test_verify_strict_fails_on_unrun(tmp_path: Path) -> None:
    """`--strict` exits 1 on any UNRUN (verification-semantics.md 7).

    The reference no longer carries one — every routine it names is built — so the case is made
    with an assertion that names an unbuilt routine.
    """
    path = tmp_path / "unrun.yaml"
    path.write_text(
        REFERENCE.read_text(encoding="utf-8")
        + "  - {id: C-99, check: leak_isolation, args: {}, modes: [normal]}\n",
        encoding="utf-8",
    )
    assert runner.invoke(app, ["verify", str(path)]).exit_code == 0
    assert runner.invoke(app, ["verify", "--strict", str(path)]).exit_code == 1


def test_verify_markdown_for_pr_comments() -> None:
    res = runner.invoke(app, ["verify", "-f", "md", str(REFERENCE)])
    assert res.output.startswith("### Prescript verify")


def test_verify_exits_one_on_fail(tmp_path: Path) -> None:
    """A GPU refresh that the surviving CDU cannot carry — the roadmap demo."""
    text = REFERENCE.read_text(encoding="utf-8").replace(
        "params: {heat_kw: 150, delta_t_k: 10",
        "params: {heat_kw: 200, delta_t_k: 10",
    )
    retrofit = tmp_path / "netlist.yaml"
    retrofit.write_text(text, encoding="utf-8")
    res = runner.invoke(app, ["verify", str(retrofit)])
    assert res.exit_code == 1
    assert "C-05@maint-cdu-A" in res.output


def test_netlist_error_exits_two(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"prescript": "0.2", "nodes": [{"id": "X"}]}), encoding="utf-8")
    res = runner.invoke(app, ["verify", str(bad)])
    assert res.exit_code == 2
