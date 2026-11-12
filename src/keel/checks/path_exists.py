"""path_exists: every load of a class is energized (optionally: through a named node)."""

from __future__ import annotations

from collections import deque

from keel.checks._util import targets
from keel.ir import Assertion, Design
from keel.modes import ModeState
from keel.result import Result, Status, unrun


def _reachable_from(design: Design, state: ModeState, start: str) -> set[str]:
    seen: set[str] = set()
    queue: deque[str] = deque([start])
    while queue:
        nid = queue.popleft()
        if nid in seen or nid not in state.energized:
            continue
        seen.add(nid)
        for e in design.edges:
            if e.src == nid and state.conducts(e):
                queue.append(e.dst)
            elif e.bidirectional and e.dst == nid and state.conducts(e):
                queue.append(e.src)
    return seen


def path_exists(design: Design, state: ModeState | None, a: Assertion) -> Result:
    mode = state.mode if state else "static"
    if state is None:
        return unrun(a.id, mode, "path_exists needs an operating mode")
    cls = str(a.args.get("class", "critical"))
    loads = targets(design, cls)
    if not loads:
        return unrun(a.id, mode, f"no loads of class '{cls}'")

    via = a.args.get("from")
    if via is not None:
        reach = _reachable_from(design, state, str(via))
        how = f"via {via}"
    else:
        reach = set(state.energized)
        how = "from any live source"

    dead = tuple(n.id for n in loads if n.id not in reach)
    subjects = tuple(n.id for n in loads)
    if dead:
        return Result(
            a.id,
            mode,
            Status.FAIL,
            f"{len(dead)}/{len(loads)} {cls} loads not energized {how}",
            subjects,
            dead,
        )
    return Result(a.id, mode, Status.PASS, f"{len(loads)} {cls} loads energized {how}", subjects)
