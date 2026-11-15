"""inlet_temp: coolant reaching each load stays below the load's maximum inlet temperature.

Screening estimate only: facility supply temperature plus the approach of the CDU that serves the
load. It ignores gain along the pipe run; the mixing at the return header is `return_temp`.
"""

from __future__ import annotations

from prescript.checks._util import targets, upstream
from prescript.ir import SOURCE_KINDS, Assertion, Design
from prescript.modes import ModeState
from prescript.result import Result, Status, unrun

METHOD = "method: approach-temperature stack-up at the cdu, steady state"


def inlet_temp(design: Design, state: ModeState | None, a: Assertion) -> Result:
    mode = state.mode if state else "static"
    if state is None:
        return unrun(a.id, mode, "inlet_temp needs an operating mode")
    cls = str(a.args.get("class", "it_liquid"))
    loads = targets(design, cls)
    if not loads:
        return unrun(a.id, mode, f"no loads of class '{cls}'")
    supply_c = state.conditions.get("facility_supply_c")
    if supply_c is None:
        return unrun(
            a.id,
            mode,
            "facility supply temperature is undecided",
            (f"mode {mode}.conditions.facility_supply_c",),
        )

    missing: list[str] = []
    offending: list[str] = []
    for load in loads:
        if load.id not in state.circulating:
            continue  # loop_closed owns that failure; do not report it twice
        limit = load.get("max_inlet_c")
        if limit is None:
            missing.append(f"{load.id}.max_inlet_c")
            continue
        approaches = [
            design.nodes[n].get("approach_k")
            for n in upstream(design, state, load.id)
            if design.nodes[n].kind in SOURCE_KINDS
        ]
        if not approaches or any(x is None for x in approaches):
            missing.append(f"{load.id}: approach_k of the cdu that supplies it")
            continue
        inlet = supply_c + max(float(x) for x in approaches)
        if inlet > float(limit):
            offending.append(f"{load.id} inlet {inlet:.0f} C > {float(limit):.0f} C")

    subjects = tuple(n.id for n in loads)
    if missing:
        return unrun(
            a.id, mode, f"{len(set(missing))} inputs are null", tuple(sorted(set(missing)))
        )
    if offending:
        return Result(
            a.id,
            mode,
            Status.FAIL,
            f"{len(offending)}/{len(loads)} {cls} loads above their inlet limit; {METHOD}",
            subjects,
            tuple(offending),
        )
    return Result(
        a.id,
        mode,
        Status.PASS,
        f"{len(loads)} {cls} loads below their inlet limit at {supply_c:.0f} C facility supply; "
        f"{METHOD}",
        subjects,
    )
