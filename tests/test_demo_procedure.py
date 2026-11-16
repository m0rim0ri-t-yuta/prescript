"""scripts/demo-procedure.sh keeps telling its story: states -> diagrams -> simulation, and a low
expansion tank that the static checks pass and the testbench fails at the step that exposes it.

It asserts the shape (exit codes, the files, a P-01 FAIL), not the figures.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "scripts" / "demo-procedure.sh"
_STEP = re.compile(r"^(\d[ab]?) .*exit (\d+)$")


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> tuple[subprocess.CompletedProcess[str], Path]:
    tmp = tmp_path_factory.mktemp("demo-procedure")
    done = subprocess.run(
        [str(DEMO)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "TMPDIR": str(tmp)},
        check=False,
    )
    return done, tmp / "prescript-demo-procedure"


def test_the_story_has_its_shape(demo: tuple[subprocess.CompletedProcess[str], Path]) -> None:
    done, _ = demo
    assert done.returncode == 0, done.stdout + done.stderr
    steps = [m.groups() for line in done.stdout.splitlines() if (m := _STEP.match(line))]
    assert steps == [("1", "0"), ("2", "0"), ("3", "0"), ("4a", "0"), ("4b", "1")]
    assert "PMP-B-1 NPSHa" in done.stdout
    assert "stop-cdu-A@s2" in done.stdout


def test_it_leaves_the_diagrams_and_charts(
    demo: tuple[subprocess.CompletedProcess[str], Path],
) -> None:
    _, work = demo
    assert (work / "storyboard" / "index.html").is_file()
    assert len(list((work / "storyboard").glob("*.svg"))) == 5  # the from-mode and four steps
    for chart in ("sim-reference.svg", "sim-low-tank.svg"):
        assert (work / chart).read_text(encoding="utf-8").startswith("<svg")
