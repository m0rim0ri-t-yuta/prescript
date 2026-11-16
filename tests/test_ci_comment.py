"""`scripts/ci_comment.py`: the pull-request comment stays inside GitHub's limit (#51).

What must hold, whatever the sizes: the body never exceeds the limit, the verdict survives every
cut that anything else can absorb, and a cut is never silent.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from prescript import engine
from prescript import report as prescript_report
from prescript.loader import load_design

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ci_comment.py"
REFERENCE = Path(__file__).resolve().parent.parent / "examples" / "gb200-1su" / "netlist.yaml"


def _module() -> ModuleType:
    """Import the script by path -- `scripts/` is not a package."""
    spec = importlib.util.spec_from_file_location("ci_comment", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ci = _module()

REPORT = "### Prescript verify — `X`\n\n**PASS 1 · FAIL 0 · WARN 0 · UNRUN 0**\n\n| id |\n|---|\n"


def _diff(lines: int) -> str:
    return "".join(f"| `~` | row {i} | heat_kw: 150 → 200 |\n" for i in range(lines))


# --- nothing to cut -------------------------------------------------------------


def test_under_the_limit_is_the_two_files_concatenated() -> None:
    diff = _diff(3)
    body, dropped = ci.compose(diff, REPORT, limit=10_000)
    assert body == diff + REPORT
    assert dropped == ""
    assert "cut to fit" not in body


def test_an_absent_change_list_leaves_the_report_alone() -> None:
    body, dropped = ci.compose("", REPORT, limit=10_000)
    assert body == REPORT
    assert dropped == ""


# --- the usual cut --------------------------------------------------------------


def test_over_the_limit_keeps_the_whole_report() -> None:
    body, dropped = ci.compose(_diff(400), REPORT, limit=2_000)
    assert REPORT in body, "the verdict is never the thing that gives way"
    assert len(body) <= 2_000
    assert dropped == _diff(400), "the full change list goes to the job log"


def test_the_cut_is_announced_with_its_size() -> None:
    diff = _diff(400)
    body, _ = ci.compose(diff, REPORT, limit=2_000)
    assert "The change list was cut to fit GitHub's comment limit" in body
    kept = body.count("heat_kw: 150 → 200")
    cut = 400 - kept
    assert f"{cut} more lines" in body
    assert "ci_netlist_diff.sh" in body, "it says where to read the full list"


def test_the_note_sits_where_the_change_list_stops() -> None:
    body, _ = ci.compose(_diff(400), REPORT, limit=2_000)
    assert body.index("cut to fit") < body.index("**PASS 1")


def test_whole_lines_are_kept() -> None:
    body, _ = ci.compose(_diff(400), REPORT, limit=2_000)
    change_lines = [line for line in body.splitlines() if "heat_kw" in line]
    assert change_lines, "something of the change list survives"
    assert all(line.endswith("|") for line in change_lines), "no half rows"


@pytest.mark.parametrize("limit", [600, 1_000, 2_000, 5_000, 20_000])
def test_the_body_never_exceeds_the_limit(limit: int) -> None:
    body, _ = ci.compose(_diff(2_000), REPORT, limit=limit)
    assert len(body) <= limit


# --- the pathological cut -------------------------------------------------------


def test_a_report_over_the_limit_keeps_its_head_and_says_so() -> None:
    """Then there is nothing left to give way, so the verdict is cut -- from the end, which keeps
    the title and the summary line."""
    report = REPORT + _diff(400)
    body, dropped = ci.compose(_diff(10), report, limit=2_000)
    assert len(body) <= 2_000
    assert "### Prescript verify" in body
    assert "**PASS 1 · FAIL 0 · WARN 0 · UNRUN 0**" in body, "the verdict itself survives"
    assert "The verdict was cut to fit GitHub's comment limit" in body
    assert dropped == _diff(10) + report, "both go to the job log"


def test_a_limit_smaller_than_the_note_still_respects_the_bound() -> None:
    body, _ = ci.compose(_diff(10), REPORT, limit=ci.RESERVE)
    assert len(body) <= ci.RESERVE


# --- characters, not bytes ------------------------------------------------------


def test_the_bound_counts_characters_not_bytes() -> None:
    """GitHub's limit is 65536 characters. A body of multibyte characters is twice that in bytes
    and still acceptable, so counting bytes would cut what did not need cutting."""
    diff = "".join(f"| `~` | 設計 {i} | 変更あり |\n" for i in range(200))
    whole = diff + REPORT
    limit = len(whole) + ci.RESERVE  # exactly enough in characters
    assert limit < len(whole.encode("utf-8")), "and not enough in bytes, which is the point"
    body, _ = ci.compose(diff, REPORT, limit=limit)
    assert body == whole, "counting bytes would have cut a body that fits"


# --- the real report ------------------------------------------------------------


def test_the_reference_report_and_a_huge_change_list_stay_inside_github_s_limit() -> None:
    design = load_design(REFERENCE)
    report = prescript_report.to_markdown(design, engine.run(design))
    body, _ = ci.compose(_diff(20_000), report, limit=ci.GITHUB_COMMENT_LIMIT)
    assert len(body) <= ci.GITHUB_COMMENT_LIMIT
    assert report in body, "the real verdict survives a change list 20 times the limit"


# --- the command line -----------------------------------------------------------


def test_the_cli_writes_the_body_and_echoes_what_it_cut(tmp_path: Path) -> None:
    diff, report, out = tmp_path / "diff.md", tmp_path / "report.md", tmp_path / "comment.md"
    diff.write_text(_diff(400), encoding="utf-8")
    report.write_text(REPORT, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, str(SCRIPT), str(diff), str(report), str(out), "--limit", "2000"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert len(out.read_text(encoding="utf-8")) <= 2_000
    assert "do not fit in 2000" in done.stderr
    assert done.stdout.count("heat_kw: 150 → 200") == 400, "the log carries every line"


def test_the_cli_is_quiet_about_a_body_that_fits(tmp_path: Path) -> None:
    diff, report, out = tmp_path / "diff.md", tmp_path / "report.md", tmp_path / "comment.md"
    diff.write_text(_diff(3), encoding="utf-8")
    report.write_text(REPORT, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, str(SCRIPT), str(diff), str(report), str(out)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.read_text(encoding="utf-8") == _diff(3) + REPORT
    assert done.stdout == ""
    assert "inside 65536" in done.stderr


def test_the_cli_survives_an_absent_change_list(tmp_path: Path) -> None:
    """`ci_netlist_diff.sh` leaves the file empty when there is nothing to compare; a missing one
    must not crash the job either."""
    report, out = tmp_path / "report.md", tmp_path / "comment.md"
    report.write_text(REPORT, encoding="utf-8")
    subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "absent.md"), str(report), str(out)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.read_text(encoding="utf-8") == REPORT
