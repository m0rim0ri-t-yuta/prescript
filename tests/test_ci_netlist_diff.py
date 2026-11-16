"""scripts/ci_netlist_diff.sh turns the netlists a PR modifies into comment sections.

The script is what .github/workflows/prescript-verify.yml runs, so the cases that must not turn a
pull request red — a design added, deleted, or left alone, a base commit that is not in a shallow
clone — are tested here against throwaway repositories rather than discovered in CI.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ci_netlist_diff.sh"
REFERENCE = ROOT / "examples" / "gb200-1su" / "netlist.yaml"
# A git hook exports GIT_DIR and GIT_INDEX_FILE, and they would aim every git call below at this
# repository instead of the throwaway one. The pre-push hook runs these tests.
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=ENV)


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        env=ENV,
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository holding the reference design at `examples/gb200-1su/netlist.yaml`."""
    repo = tmp_path / "repo"
    (repo / "examples" / "gb200-1su").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "examples" / "gb200-1su" / "netlist.yaml").write_text(
        REFERENCE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return repo


def _run(repo: Path, base: str) -> tuple[subprocess.CompletedProcess[str], str]:
    out = repo / "diff.md"
    res = subprocess.run(
        [str(SCRIPT), base, str(out)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env=ENV,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    return res, out.read_text(encoding="utf-8")


def test_a_modified_netlist_becomes_a_diff_section(repo: Path) -> None:
    base = _commit(repo, "base")
    netlist = repo / "examples" / "gb200-1su" / "netlist.yaml"
    netlist.write_text(
        netlist.read_text(encoding="utf-8").replace("heat_kw: 150", "heat_kw: 200"),
        encoding="utf-8",
    )
    _commit(repo, "a GPU refresh")

    _, body = _run(repo, base)
    assert body.startswith("### Prescript diff — `GB200-1SU-DLC-POC`")
    assert "heat_kw: 150 → 200" in body
    assert "RACK-01" in body and "RACK-08" in body
    # The diff states facts; the verdict is the verify step's.
    assert "A change list, not a verdict" in body
    assert "FAIL" not in body


def test_every_modified_netlist_gets_its_own_section(repo: Path) -> None:
    second = repo / "examples" / "second-hall" / "netlist.yaml"
    second.parent.mkdir()
    second.write_text(
        REFERENCE.read_text(encoding="utf-8").replace("GB200-1SU-DLC-POC", "SECOND-HALL"),
        encoding="utf-8",
    )
    base = _commit(repo, "base")
    for netlist in (repo / "examples" / "gb200-1su" / "netlist.yaml", second):
        netlist.write_text(
            netlist.read_text(encoding="utf-8").replace("heat_kw: 150", "heat_kw: 200"),
            encoding="utf-8",
        )
    _commit(repo, "a GPU refresh in both halls")

    _, body = _run(repo, base)
    assert body.count("### Prescript diff") == 2
    assert "`GB200-1SU-DLC-POC`" in body and "`SECOND-HALL`" in body


def test_an_added_netlist_is_skipped(repo: Path) -> None:
    """A PR that introduces a design has no base side to compare — and must not go red."""
    base = _commit(repo, "base")
    added = repo / "examples" / "new-hall" / "netlist.yaml"
    added.parent.mkdir()
    added.write_text(REFERENCE.read_text(encoding="utf-8"), encoding="utf-8")
    _commit(repo, "a second design")

    res, body = _run(repo, base)
    assert body == ""
    assert "nothing to diff" in res.stdout


def test_a_deleted_netlist_is_skipped(repo: Path) -> None:
    base = _commit(repo, "base")
    _git(repo, "rm", "-q", "-r", "examples/gb200-1su")
    _commit(repo, "retire the design")

    _, body = _run(repo, base)
    assert body == ""


def test_a_pr_that_touches_no_netlist_is_skipped(repo: Path) -> None:
    base = _commit(repo, "base")
    (repo / "README.md").write_text("docs only\n", encoding="utf-8")
    _commit(repo, "docs only")

    _, body = _run(repo, base)
    assert body == ""


def test_a_base_outside_the_clone_is_skipped_with_the_reason(repo: Path) -> None:
    """A shallow checkout has no base commit; say so instead of failing the job."""
    _commit(repo, "base")
    res, body = _run(repo, "0" * 40)
    assert body == ""
    assert "fetch-depth: 0" in res.stderr


def test_a_base_netlist_that_cannot_be_read_becomes_a_bounded_note(repo: Path) -> None:
    """The head side is the verify step's business, so a broken base is a note, not a red job."""
    netlist = repo / "examples" / "gb200-1su" / "netlist.yaml"
    netlist.write_text("design: {\n", encoding="utf-8")
    base = _commit(repo, "a base that does not parse")
    netlist.write_text(REFERENCE.read_text(encoding="utf-8"), encoding="utf-8")
    _commit(repo, "fix the design")

    _, body = _run(repo, base)
    assert "could not compare this netlist against the base" in body
    assert "examples/gb200-1su/netlist.yaml" in body
    # Bounded: a YAML error arrives as a rich traceback, and a comment is not a log.
    assert len(body.splitlines()) < 30
