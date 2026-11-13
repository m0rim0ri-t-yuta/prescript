"""loop_closed: every load of a class sits on a closed loop back to the CDU that supplies it.

Cooling differs from power here: a supply path that cannot return is not a path. A load that is
reachable from a running CDU but whose return leg is isolated still overheats.
"""

from __future__ import annotations

from collections import deque

from prescript.checks._util import targets
from prescript.ir import SOURCE_KINDS, Assertion, Design
from prescript.modes import ModeState
from prescript.result import Result, Status, unrun


def _forward(design: Design, state: ModeState, start: str) -> set[str]:
    """Everything the fluid leaving `start` can reach in this mode, `start` included if it loops."""
    seen: set[str] = set()
    queue: deque[str] = deque([start])
    while queue:
        for edge in state.outlets(design, queue.popleft()):
            if edge.dst in seen:
                continue
            seen.add(edge.dst)
            queue.append(edge.dst)
    return seen


def loop_closed(design: Design, state: ModeState | None, a: Assertion) -> Result:
    mode = state.mode if state else "static"
    if state is None:
        return unrun(a.id, mode, "loop_closed needs an operating mode")
    cls = str(a.args.get("class", "it_liquid"))
    loads = targets(design, cls)
    if not loads:
        return unrun(a.id, mode, f"no loads of class '{cls}'")
    via = a.args.get("via")

    offending: list[str] = []
    for load in loads:
        if load.id not in state.circulating:
            offending.append(f"{load.id} (no supply)")
            continue
        reach = _forward(design, state, load.id)
        if load.id not in reach:
            offending.append(f"{load.id} (no return path)")
        elif not any(design.nodes[n].kind in SOURCE_KINDS for n in reach):
            offending.append(f"{load.id} (loop reaches no cdu)")
        elif via is not None and str(via) not in reach:
            offending.append(f"{load.id} (loop does not pass {via})")

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
