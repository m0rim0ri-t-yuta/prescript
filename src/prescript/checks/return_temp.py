"""return_temp: the mixed return reaching each running CDU stays inside the CDU's design range.

`inlet_temp` looks at the side leaving the CDU. The return matters as much: the exchanger is
selected for a return range, and outside it the approach `inlet_temp` relies on no longer holds.

Screening estimate, named in every result. Each load's outlet is its inlet — facility supply plus
the approach of the CDU that serves it, the same stack-up as `inlet_temp` — plus its `delta_t_k`.
A demand factor scales a load's flow, not its temperature rise, because flow is what
`Q = V * rho * cp * dT` gives at a fixed `dT`. The outlets are mixed in proportion to the flow each
load sends back to each CDU, along the same return legs and shares `accumulate` uses. Heat gained
or lost along the pipes and any bypass control are not modelled.
"""

from __future__ import annotations

from prescript.checks._util import legs, load_quantity, upstream
from prescript.ir import LOAD_KINDS, SOURCE_KINDS, Assertion, Design
from prescript.modes import ModeState
from prescript.result import Result, Status, unrun

METHOD = "method: flow-weighted mixing of load outlets, approach stack-up at the cdu, steady state"


def return_temp(design: Design, state: ModeState | None, a: Assertion) -> Result:
    mode = state.mode if state else "static"
    if state is None:
        return unrun(a.id, mode, "return_temp needs an operating mode")
    kinds = sorted(str(k) for k in a.args.get("kinds", ["cdu"]))
    cdus = sorted((n for n in design.nodes_of(kinds) if n.kind in SOURCE_KINDS), key=lambda n: n.id)
    if not cdus:
        return unrun(a.id, mode, f"no cdus among kinds {kinds}")
    supply_c = state.conditions.get("facility_supply_c")
    if supply_c is None:
        return unrun(
            a.id,
            mode,
            "facility supply temperature is undecided",
            (f"mode {mode}.conditions.facility_supply_c",),
        )
    loads = sorted(
        (n for n in design.nodes.values() if n.kind in LOAD_KINDS and n.id in state.circulating),
        key=lambda n: n.id,
    )
    if not loads:
        return unrun(a.id, mode, "no loads are circulating")

    missing: list[str] = []
    flow: dict[str, float] = {}
    heat: dict[str, float] = {}  # sum of flow x outlet temperature, per receiving cdu
    for load in loads:
        qty, gaps = load_quantity(design, state, load, "flow")
        missing += gaps
        approaches = [
            design.nodes[n].get("approach_k")
            for n in upstream(design, state, load.id)
            if design.nodes[n].kind in SOURCE_KINDS
        ]
        if not approaches or any(x is None for x in approaches):
            missing.append(f"{load.id}: approach_k of the cdu that supplies it")
            continue
        if qty is None:
            continue
        outlet = supply_c + max(float(x) for x in approaches) + float(load.get("delta_t_k"))
        for weight, edges in legs(design, state, load.id, outward=True):
            receiver = edges[-1].dst
            flow[receiver] = flow.get(receiver, 0.0) + qty * weight
            heat[receiver] = heat.get(receiver, 0.0) + qty * weight * outlet

    evaluated = [c for c in cdus if flow.get(c.id, 0.0) > 0.0]
    for cdu in evaluated:
        for key in ("return_min_c", "return_max_c"):
            if cdu.get(key) is None:
                missing.append(f"{cdu.id}.{key}")
    if missing:
        return unrun(
            a.id, mode, f"{len(set(missing))} inputs are null", tuple(sorted(set(missing)))
        )
    if not evaluated:
        return unrun(a.id, mode, "no running cdu receives a return")

    offending: list[str] = []
    mixes: list[float] = []
    for cdu in evaluated:
        mixed = heat[cdu.id] / flow[cdu.id]
        mixes.append(mixed)
        low, high = float(cdu.get("return_min_c")), float(cdu.get("return_max_c"))
        if mixed > high:
            offending.append(f"{cdu.id} mixed return {mixed:.1f} C > {high:.1f} C")
        elif mixed < low:
            offending.append(f"{cdu.id} mixed return {mixed:.1f} C < {low:.1f} C")

    subjects = tuple(c.id for c in evaluated)
    if offending:
        return Result(
            a.id,
            mode,
            Status.FAIL,
            f"{len(offending)}/{len(evaluated)} cdus outside their return range; {METHOD}",
            subjects,
            tuple(offending),
        )
    return Result(
        a.id,
        mode,
        Status.PASS,
        f"{len(evaluated)} cdus see a mixed return inside their range, warmest {max(mixes):.1f} C"
        f"; {METHOD}",
        subjects,
    )
