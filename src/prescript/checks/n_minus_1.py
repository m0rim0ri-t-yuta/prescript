"""n_minus_1: every load of a class keeps a closed loop when any one element is stopped.

The sweep stops one element at a time, resolves the mode again and applies the same loop test as
`loop_closed`. Two kinds of element are never swept: loads, because they are what the sweep
protects, and anything that carries no flow in this mode already (a standby pump, a dead leg, the
side of a CDU that maintenance has taken out) — there is nothing there to drop, so stopping it
could not change any result.

The IR is frozen. Stopping an element builds a new `Mode` whose overrides are the states this
mode had already resolved to, plus the one element set to `off`; the design itself is untouched.
"""

from __future__ import annotations

from prescript.checks._util import loop_break, targets
from prescript.ir import LOAD_KINDS, NODE_KINDS, Assertion, Design, Mode, Node
from prescript.modes import ModeState, resolve
from prescript.result import Result, Status, unrun


def _carries_flow(state: ModeState, node_id: str) -> bool:
    """A node on a live circuit: a running CDU reaches it and it reaches a running CDU back."""
    return node_id in state.circulating and node_id in state.draining


def _sweep(design: Design, state: ModeState, kinds: set[str]) -> list[Node]:
    return sorted(
        (
            n
            for n in design.nodes.values()
            if n.kind in kinds and n.kind not in LOAD_KINDS and _carries_flow(state, n.id)
        ),
        key=lambda n: n.id,
    )


def _stopped(design: Design, state: ModeState, node_id: str) -> ModeState:
    """This mode with one more element stopped, resolved from scratch."""
    overrides = {**state.node_state, **state.device_state, node_id: "off"}
    return resolve(
        design,
        Mode(
            name=f"{state.mode} -{node_id}",
            overrides=overrides,
            demand=state.demand,
            conditions=state.conditions,
        ),
    )


def n_minus_1(design: Design, state: ModeState | None, a: Assertion) -> Result:
    mode = state.mode if state else "static"
    if state is None:
        return unrun(a.id, mode, "n_minus_1 needs an operating mode")
    cls = str(a.args.get("class", "it_liquid"))
    loads = targets(design, cls)
    if not loads:
        return unrun(a.id, mode, f"no loads of class '{cls}'")
    kinds = {str(k) for k in a.args.get("sweep", sorted(NODE_KINDS - LOAD_KINDS))}
    swept = _sweep(design, state, kinds)
    if not swept:
        return unrun(a.id, mode, f"nothing of kind {'/'.join(sorted(kinds))} carries flow here")

    broken_by: list[tuple[str, list[str]]] = []
    for element in swept:
        reduced = _stopped(design, state, element.id)
        broken = [n.id for n in loads if loop_break(design, reduced, n) is not None]
        if broken:
            broken_by.append((element.id, broken))

    subjects = tuple(n.id for n in swept)
    if broken_by:
        if len(broken_by) == 1:
            stopped, lost = broken_by[0]
            detail = (
                f"stopping {stopped} leaves {len(lost)}/{len(loads)} "
                f"{cls} loads without a closed loop"
            )
        else:
            detail = (
                f"{len(broken_by)}/{len(swept)} elements leave {cls} loads without a closed loop"
            )
        offending = tuple(f"{stopped}: {', '.join(lost)}" for stopped, lost in broken_by)
        return Result(a.id, mode, Status.FAIL, detail, subjects, offending)
    kept = f"{len(loads)} {cls} loads keep a closed loop"
    return Result(
        a.id, mode, Status.PASS, f"{kept} with any one of {len(swept)} elements stopped", subjects
    )
