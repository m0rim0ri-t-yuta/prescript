"""loop_closed: every load of a class sits on a closed loop back to the CDU that supplies it.

Cooling differs from power here: a supply path that cannot return is not a path. A load that is
reachable from a running CDU but whose return leg is isolated still overheats. The loop test
itself lives in `_util.loop_break`, because `n_minus_1` applies the same rule element by element.
"""

from __future__ import annotations

from prescript.checks._util import loop_break, targets
from prescript.ir import Assertion, Design
from prescript.modes import ModeState
from prescript.result import Result, Status, unrun


def loop_closed(design: Design, state: ModeState | None, a: Assertion) -> Result:
    mode = state.mode if state else "static"
    if state is None:
        return unrun(a.id, mode, "loop_closed needs an operating mode")
    cls = str(a.args.get("class", "it_liquid"))
    loads = targets(design, cls)
    if not loads:
        return unrun(a.id, mode, f"no loads of class '{cls}'")
    raw_via = a.args.get("via")
    via = str(raw_via) if raw_via is not None else None

    offending: list[str] = []
    for load in loads:
        why = loop_break(design, state, load, via)
        if why is not None:
            offending.append(f"{load.id} ({why})")

    how = f"through {via}" if via is not None else "back to a cdu"
    subjects = tuple(n.id for n in loads)
    if offending:
        return Result(
            a.id,
            mode,
            Status.FAIL,
            f"{len(offending)}/{len(loads)} {cls} loads have no closed loop {how}",
            subjects,
            tuple(offending),
        )
    return Result(a.id, mode, Status.PASS, f"{len(loads)} {cls} loads loop {how}", subjects)
