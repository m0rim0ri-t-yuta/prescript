"""dual_path: every dual-fed load of a class is energized from each named side."""

from __future__ import annotations

from prescript.checks._util import node_side, targets
from prescript.ir import Assertion, Design
from prescript.modes import ModeState
from prescript.result import Result, Status, unrun


def dual_path(design: Design, state: ModeState | None, a: Assertion) -> Result:
    mode = state.mode if state else "static"
    if state is None:
        return unrun(a.id, mode, "dual_path needs an operating mode")
    cls = str(a.args.get("class", "critical"))
    sides = [str(s) for s in a.args.get("sides", ["A", "B"])]
    loads = [n for n in targets(design, cls) if n.get("dual_fed")]
    if not loads:
        return unrun(a.id, mode, f"no dual-fed loads of class '{cls}'")

    offending: list[str] = []
    for load in loads:
        live_sides = {node_side(design.nodes[e.src], sides) for e in state.feeds(design, load.id)}
        lost = [s for s in sides if s not in live_sides]
        if lost:
            offending.append(f"{load.id} (no live side {'/'.join(lost)})")

    subjects = tuple(n.id for n in loads)
    if offending:
        return Result(
            a.id,
            mode,
            Status.FAIL,
            f"{len(offending)}/{len(loads)} {cls} loads lost a side",
            subjects,
            tuple(offending),
        )
    return Result(
        a.id,
        mode,
        Status.PASS,
        f"{len(loads)} {cls} loads fed from {'+'.join(sides)}",
        subjects,
    )
