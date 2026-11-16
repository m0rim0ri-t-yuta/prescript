"""Run every cooling assertion in every mode it names and collect results.

The loop is the core's (`prescript.core.engine`); the cooling domain supplies its routines, the
circulation of each mode (`prescript.modes.resolve`) and `coverage`, which runs over the other
results.
"""

from __future__ import annotations

from prescript.checks import PLANNED, REGISTRY
from prescript.core import engine as core
from prescript.ir import META_MODE, Assertion, Design
from prescript.modes import ModeState, resolve
from prescript.result import Result, Status, unrun


def _coverage(a: Assertion, results: list[Result]) -> Result:
    cells = [r for r in results if r.mode != META_MODE]
    if not cells:
        return unrun(a.id, META_MODE, "nothing to cover")
    ran = [r for r in cells if r.status is not Status.UNRUN]
    gaps = tuple(f"{r.assertion}@{r.mode}" for r in cells if r.status is Status.UNRUN)
    pct = 100.0 * len(ran) / len(cells)
    detail = f"{len(ran)}/{len(cells)} assertion x mode cells ran ({pct:.0f}%)"
    if gaps:
        return Result(a.id, META_MODE, Status.FAIL, detail, offending=gaps)
    return Result(a.id, META_MODE, Status.PASS, detail)


def run(design: Design) -> list[Result]:
    def state(mode: str) -> ModeState:
        return resolve(design, design.modes[mode])

    return core.run(design, REGISTRY, state, planned=PLANNED, post={"coverage": _coverage})
