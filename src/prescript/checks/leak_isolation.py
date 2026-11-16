"""leak_isolation: a leaking branch can be valved off without stopping another running load.

For each swept element the routine finds its isolation zone: everything it is joined to by edges
that carry no valve, followed in either direction, because a leak drains both ways. The valves on
the edges that leave the zone are its boundary. Closing them all is what an operator would do, so
the mode is resolved again with them shut and every load that had a closed loop before is asked
the `loop_closed` question again. The swept element itself is expected to stop; any other load
that loses its loop is collateral, and so is a zone with a CDU inside it, because then the leak
can only be stopped by stopping the CDU.

Only `kind: valve` bounds a zone. A check valve cannot be closed by hand, so it joins what is on
either side of it. Topology only: the valves are assumed to shut tight, and draining the zone,
refilling it and the time it takes are not judged.
"""

from __future__ import annotations

from collections import deque

from prescript.checks._util import loop_break, with_overrides
from prescript.ir import LOAD_KINDS, SOURCE_KINDS, Assertion, Design, Edge, Node
from prescript.modes import ModeState
from prescript.result import Result, Status, unrun

METHOD = "method: valve-bounded zones, every boundary valve shut tight, one leak at a time"


def _isolates(edge: Edge) -> bool:
    return edge.via is not None and edge.via.kind == "valve"


def zone(design: Design, node_id: str) -> tuple[set[str], list[Edge]]:
    """The nodes joined to `node_id` without a valve between them, and the valved edges that
    leave that set (its boundary)."""
    neighbours: dict[str, list[str]] = {nid: [] for nid in design.nodes}
    for edge in design.edges:
        if not _isolates(edge):
            neighbours[edge.src].append(edge.dst)
            neighbours[edge.dst].append(edge.src)
    inside: set[str] = {node_id}
    queue: deque[str] = deque([node_id])
    while queue:
        for nid in neighbours[queue.popleft()]:
            if nid not in inside:
                inside.add(nid)
                queue.append(nid)
    boundary = [
        e for e in design.edges if _isolates(e) and ((e.src in inside) != (e.dst in inside))
    ]
    return inside, boundary


def _swept(design: Design, kinds: set[str], cls: str) -> list[Node]:
    return sorted(
        (
            n
            for n in design.nodes.values()
            if n.kind in kinds and (n.kind not in LOAD_KINDS or n.get("class") == cls)
        ),
        key=lambda n: n.id,
    )


def leak_isolation(design: Design, state: ModeState | None, a: Assertion) -> Result:
    mode = state.mode if state else "static"
    if state is None:
        return unrun(a.id, mode, "leak_isolation needs an operating mode")
    cls = str(a.args.get("class", "it_liquid"))
    kinds = {str(k) for k in a.args.get("sweep", sorted(LOAD_KINDS))}
    swept = _swept(design, kinds, cls)
    if not swept:
        what = f"{cls} loads" if kinds <= LOAD_KINDS else f"kind {'/'.join(sorted(kinds))}"
        return unrun(a.id, mode, f"nothing to sweep: no {what}")

    loads = sorted((n for n in design.nodes.values() if n.kind in LOAD_KINDS), key=lambda n: n.id)
    running = [n for n in loads if loop_break(design, state, n) is None]
    if not running:
        return unrun(a.id, mode, "no load has a closed loop here, so a leak could stop nothing")

    offending: list[str] = []
    most_valves = 0
    for element in swept:
        inside, boundary = zone(design, element.id)
        cdus = sorted(n for n in inside if design.nodes[n].kind in SOURCE_KINDS)
        if cdus:
            offending.append(f"{element.id}: no valve between it and {', '.join(cdus)}")
            continue
        valves = sorted({e.via.id for e in boundary if e.via is not None})
        most_valves = max(most_valves, len(valves))
        shut = with_overrides(
            design, state, dict.fromkeys(valves, "closed"), f"{state.mode} x{element.id}"
        )
        stopped = [
            n.id for n in running if n.id != element.id and loop_break(design, shut, n) is not None
        ]
        if stopped:
            offending.append(f"{element.id}: stops {', '.join(stopped)}")

    what = f"{cls} loads" if kinds <= LOAD_KINDS else f"elements of kind {'/'.join(sorted(kinds))}"
    subjects = tuple(n.id for n in swept)
    if offending:
        detail = (
            f"{len(offending)}/{len(swept)} {what} cannot be valved off without stopping "
            f"another load; {METHOD}"
        )
        return Result(a.id, mode, Status.FAIL, detail, subjects, tuple(offending))
    detail = (
        f"{len(swept)} {what} can each be valved off (up to {most_valves} valves) without "
        f"stopping any of {len(running)} running loads; {METHOD}"
    )
    return Result(a.id, mode, Status.PASS, detail, subjects)
