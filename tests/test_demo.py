"""scripts/demo.sh keeps telling the W4 story: green, then red with findings, then green again.

It asserts the shape, not the totals — those move whenever a check routine lands.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "scripts" / "demo.sh"
REFERENCE = ROOT / "examples" / "gb200-1su" / "netlist.yaml"
_STEP = re.compile(r"^(\d) .*exit (\d+)$")


def _run(tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(DEMO)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "TMPDIR": str(tmp_path), **env},
        check=False,
    )


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess[str]:
    return _run(tmp_path_factory.mktemp("demo"))


def test_demo_goes_green_red_green(demo: subprocess.CompletedProcess[str]) -> None:
    assert demo.returncode == 0, demo.stdout + demo.stderr
    steps = [m.groups() for line in demo.stdout.splitlines() if (m := _STEP.match(line))]
    assert steps == [("1", "0"), ("2", "1"), ("3", "0")]


def test_the_red_step_shows_its_own_evidence(demo: subprocess.CompletedProcess[str]) -> None:
    assert "FAIL   C-05@maint-cdu-A" in demo.stdout
    assert "CDU-B 2602/2300 L/min (113%)" in demo.stdout
    assert "CDU-B 1720/1500 kW (115%)" in demo.stdout


def test_warn_evidence_is_not_shown_under_a_fail(demo: subprocess.CompletedProcess[str]) -> None:
    """C-14 (null ratings) and C-15 (coverage gaps) are WARNs; their items are not FAIL evidence."""
    assert "rating_kpa" not in demo.stdout
    assert "C-09@normal" not in demo.stdout


def test_the_reference_design_is_not_modified(tmp_path: Path) -> None:
    before = hashlib.sha256(REFERENCE.read_bytes()).hexdigest()
    assert _run(tmp_path).returncode == 0
    assert hashlib.sha256(REFERENCE.read_bytes()).hexdigest() == before


def test_a_netlist_that_no_longer_matches_stops_the_demo(tmp_path: Path) -> None:
    """A reformatted rack block must stop the demo, not show a refresh that never happened."""
    changed = tmp_path / "netlist.yaml"
    changed.write_text(
        REFERENCE.read_text(encoding="utf-8").replace("heat_kw: 150,", "heat_kw: 150.0,"),
        encoding="utf-8",
    )
    res = _run(tmp_path, PRESCRIPT_DEMO_NETLIST=str(changed))
    assert res.returncode == 1
    assert "nothing matched 's/heat_kw: 150,/heat_kw: 200,/'" in res.stderr
