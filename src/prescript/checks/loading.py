"""loading: no element carries more than its rating in this mode, on a flow or a heat basis.

Flow and heat are accumulated from the loads around the loop that serves them
(`_util.accumulate`). This is a steady-state sensible-heat balance, not a hydraulic solution:
whether each load gets its share is `balance`, and whether the pump can push it is
`pressure_drop`.
"""

from __future__ import annotations

from prescript.checks._util import RATING_OF, UNIT_OF, accumulate
from prescript.ir import LOAD_KINDS, Assertion, Design
from prescript.modes import ModeState
from prescript.result import Result, Status, unrun

METHOD = "method: steady-state sensible heat, share-weighted loop accumulation"


def loading(design: Design, state: ModeState | None, a: Assertion) -> Result:
    mode = state.mode if state else "static"
    if state is None:
        return unrun(a.id, mode, "loading needs an operating mode")
    basis = str(a.args.get("basis", "flow"))
    if basis not in RATING_OF:
        return unrun(a.id, mode, f"unknown basis '{basis}'")
    kinds = {str(k) for k in a.args.get("kinds", [])}
    limit = float(a.args.get("limit", 1.0))

    subjects = sorted(design.nodes_of(sorted(kinds)), key=lambda n: n.id)
    if not subjects:
        return unrun(a.id, mode, f"no elements of kinds {sorted(kinds)}")
    loads = sorted(
        (n for n in design.nodes.values() if n.kind in LOAD_KINDS and n.id in state.circulating),
        key=lambda n: n.id,
    )
    if not loads:
        return unrun(a.id, mode, "no loads are circulating")

    totals, missing = accumulate(design, state, loads, basis)
    rating_key, unit = RATING_OF[basis], UNIT_OF[basis]
    offending: list[str] = []
    worst = 0.0
    for node in subjects:
        rating = node.get(rating_key)
        if rating is None:
            missing.append(f"{node.id}.{rating_key}")
            continue
        carried = totals.get(node.id, 0.0)
        ratio = carried / float(rating)
        worst = max(worst, ratio)
        if ratio > limit:
            offending.append(f"{node.id} {carried:.0f}/{float(rating):.0f} {unit} ({ratio:.0%})")

    ids = tuple(n.id for n in subjects)
    if missing:
        return unrun(
            a.id, mode, f"{len(set(missing))} inputs are null", tuple(sorted(set(missing)))
        )
    if offending:
        return Result(
            a.id,
            mode,
            Status.FAIL,
            f"{len(offending)}/{len(subjects)} elements over {limit:.0%} of {unit} rating; "
            f"{METHOD}",
            ids,
            tuple(offending),
        )
    return Result(
        a.id,
        mode,
        Status.PASS,
        f"{len(subjects)} elements within {unit} rating, worst {worst:.0%}; {METHOD}",
        ids,
    )
