"""ride_through: the water already in the loop carries the load long enough.

`facility-loss` takes the heat rejection away — the facility water is gone and both CDUs trip —
and the mode's note asks how long until the GPUs must throttle. What answers it is the coolant
already in the loop: its heat capacity divided by the heat the mode leaves on.

Screening estimate, named in every result: one lumped inventory at one temperature, rising
adiabatically from the mode's `loop_start_c` to the tightest `max_inlet_c` on that loop. Only the
heat sink is assumed lost, not circulation, so the whole connected inventory counts; a valve this
mode shuts still isolates what is behind it. The metal mass of pipes, plates and exchangers is
ignored, which under-states the time, and so is heat lost to the hall, which over-states it. A
transient temperature profile, and whether the pumps are on a UPS at all, are out of scope.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from prescript.checks._util import targets
from prescript.ir import LOAD_KINDS, Assertion, Design, Node
from prescript.modes import ModeState
from prescript.result import Result, Status, unrun

METHOD = (
    "method: lumped loop inventory, adiabatic rise to the tightest inlet limit, "
    "heat rejection lost and circulation assumed"
)


def _connected(design: Design, state: ModeState, start: str) -> frozenset[str]:
    """Everything hydraulically connected to `start` through the valves this mode leaves open."""
    seen = {start}
    queue: deque[str] = deque([start])
    while queue:
        node_id = queue.popleft()
        for edge in [*design.incoming(node_id), *design.outgoing(node_id)]:
            if not state.conducts(edge):
                continue
            neighbour = edge.src if edge.dst == node_id else edge.dst
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return frozenset(seen)


def _volume_l(node: Node) -> float | None:
    """Litres the element holds. A pipe states its bore and run, so its volume is geometry."""
    stated = node.get("volume_l")
    if stated is not None:
        return float(stated)
    dn, length = node.get("dn_mm"), node.get("length_m")
    if dn is None or length is None:
        return None
    return math.pi * (float(dn) / 1000.0) ** 2 / 4.0 * float(length) * 1000.0


class _Loop:
    """One hydraulically connected inventory and the loads sitting in it."""

    def __init__(self, design: Design, state: ModeState, members: frozenset[str], cls: str) -> None:
        self.cls = cls
        self.missing: list[str] = []
        self.litres = 0.0
        self.heat_kw = 0.0
        self.limit_c: float | None = None
        self.limited_by = ""
        for node_id in sorted(members):
            node = design.nodes[node_id]
            volume = _volume_l(node)
            if volume is None:
                self.missing.append(f"{node_id}.volume_l")
            else:
                self.litres += volume
            if node.kind in LOAD_KINDS:
                self._add_load(state, node)

    def _add_load(self, state: ModeState, node: Node) -> None:
        """Every load on the loop heats the same water; only the class under test sets the limit."""
        heat = node.get("heat_kw")
        if heat is None:
            self.missing.append(f"{node.id}.heat_kw")
        else:
            self.heat_kw += float(heat) * state.demand_factor(node.get("class"))
        if node.get("class") != self.cls:
            return
        limit = node.get("max_inlet_c")
        if limit is None:
            self.missing.append(f"{node.id}.max_inlet_c")
        elif self.limit_c is None or float(limit) < self.limit_c:
            self.limit_c, self.limited_by = float(limit), node.id

    def seconds(self, volumetric_kj_lk: float, start_c: float, limit_c: float) -> float:
        """Time to the tightest limit. Already at it, or past it, is zero."""
        return self.litres * volumetric_kj_lk * max(limit_c - start_c, 0.0) / self.heat_kw


@dataclass(frozen=True)
class _Judged:
    """One loop, with the numbers a result has to quote."""

    name: str
    seconds: float
    heat_kw: float
    litres: float
    limit_c: float
    limited_by: str


def ride_through(design: Design, state: ModeState | None, a: Assertion) -> Result:
    mode = state.mode if state else "static"
    if state is None:
        return unrun(a.id, mode, "ride_through needs an operating mode")
    required = a.args.get("must_exceed_s")
    if required is None:
        return unrun(a.id, mode, "the time to beat is undecided", (f"{a.id}.must_exceed_s",))
    must_exceed = float(required)
    cls = str(a.args.get("class", "it_liquid"))
    loads = targets(design, cls)
    if not loads:
        return unrun(a.id, mode, f"no loads of class '{cls}'")
    start_c = state.conditions.get("loop_start_c")
    if start_c is None:
        return unrun(
            a.id,
            mode,
            "the loop temperature when the heat sink is lost is undecided",
            (f"mode {mode}.conditions.loop_start_c",),
        )

    missing: list[str] = []
    loops: dict[frozenset[str], str] = {}  # the loop, named after the first load in it
    for load in loads:
        loops.setdefault(_connected(design, state, load.id), load.id)

    judged: list[_Judged] = []
    for members, name in loops.items():
        loop = _Loop(design, state, members, cls)
        fluid = design.fluid_of(design.nodes[name])
        volumetric = fluid.volumetric_heat_kj_lk() if fluid is not None else None
        if fluid is None:
            loop.missing.append(f"{name}.fluid")
        elif volumetric is None:
            loop.missing.append(f"fluid {fluid.name}.cp_kj_kgk/density_kg_l")
        missing += loop.missing
        if loop.missing or volumetric is None or loop.limit_c is None:
            continue
        if loop.heat_kw <= 0.0:
            continue  # nothing left on this loop to carry
        judged.append(
            _Judged(
                name,
                loop.seconds(volumetric, start_c, loop.limit_c),
                loop.heat_kw,
                loop.litres,
                loop.limit_c,
                loop.limited_by,
            )
        )

    if missing:
        unique = tuple(sorted(set(missing)))
        return unrun(a.id, mode, f"{len(unique)} inputs are null", unique)
    if not judged:
        return unrun(a.id, mode, "no loop carries heat in this mode")

    subjects = tuple(j.name for j in judged)
    offending = tuple(
        f"{j.name}'s loop: {j.seconds:.0f} s < {must_exceed:.0f} s "
        f"({j.heat_kw:.0f} kW into {j.litres:.0f} L, {start_c:.0f} → {j.limit_c:.0f} C)"
        for j in judged
        if j.seconds < must_exceed
    )
    if offending:
        return Result(
            a.id,
            mode,
            Status.FAIL,
            f"{len(offending)}/{len(judged)} loops fall short of {must_exceed:.0f} s; {METHOD}",
            subjects,
            offending,
        )
    tightest = min(judged, key=lambda j: j.seconds)
    return Result(
        a.id,
        mode,
        Status.PASS,
        f"{len(judged)} loops checked; the tightest holds {tightest.heat_kw:.0f} kW for "
        f"{tightest.seconds:.0f} s, over the {must_exceed:.0f} s required (first to its limit: "
        f"{tightest.limited_by} at {tightest.limit_c:.0f} C); {METHOD}",
        subjects,
    )
