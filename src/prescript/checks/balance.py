"""balance: every load of a class gets the flow it requires, within a tolerance.

`loading` sums what each element has to carry; it says nothing about whether each rack gets its
own share. A hall can be within every rating and still starve one rack, and the rack that is
starved is the one that throttles.

The method is a screening one, named in every result. Each load's requirement is split over its
supply legs (and its return legs) exactly as `accumulate` splits it, by edge `share`. A leg can
deliver only as much as the tightest rating on it allows, so the leg's share is scaled by
`min(1, rating / carried)` of its most loaded element, and what the load gets is the sum over its
legs — limited by the worse of the two sides. That is a rating-limited screening, not a hydraulic
solution: it does not solve for pressure, so it cannot tell how a real loop would redistribute
flow around the bottleneck. Nothing here does — `pressure_drop` is a screening too, not a solver.
"""

from __future__ import annotations

from prescript.checks._util import Leg, accumulate, legs, load_quantity, targets
from prescript.ir import LOAD_KINDS, SOURCE_KINDS, Assertion, Design
from prescript.modes import ModeState
from prescript.result import Result, Status, unrun

METHOD = "method: share-weighted legs capped by their tightest rating, no pressure solution"

Path = tuple[float, tuple[str, ...]]


def _elements(design: Design, legs_: list[Leg], *, outward: bool) -> list[Path]:
    """The elements each leg passes, with its share of the flow.

    The return side stops before the CDU, because the supply side is where the CDU itself is
    charged — the same cut `accumulate` makes so nothing is counted twice.
    """
    if outward:
        return [
            (w, tuple(e.dst for e in edges if design.nodes[e.dst].kind not in SOURCE_KINDS))
            for w, edges in legs_
        ]
    return [(w, tuple(e.src for e in edges)) for w, edges in legs_]


def _deliverable(paths: list[Path], totals: dict[str, float], ratings: dict[str, float]) -> float:
    """Fraction of the requirement these legs can deliver, each capped by its tightest rating."""
    delivered = 0.0
    for weight, elements in paths:
        caps = [min(1.0, ratings[e] / totals[e]) for e in elements if totals.get(e, 0.0) > 0.0]
        delivered += weight * min(caps, default=1.0)
    return delivered


def balance(design: Design, state: ModeState | None, a: Assertion) -> Result:
    mode = state.mode if state else "static"
    if state is None:
        return unrun(a.id, mode, "balance needs an operating mode")
    cls = str(a.args.get("class", "it_liquid"))
    tolerance = float(a.args.get("tolerance_pct", 10)) / 100.0
    loads = targets(design, cls)
    if not loads:
        return unrun(a.id, mode, f"no loads of class '{cls}'")

    missing: list[str] = []
    required: dict[str, float] = {}
    for load in loads:
        qty, gaps = load_quantity(design, state, load, "flow")
        missing += gaps
        if qty is not None:
            required[load.id] = qty

    # What an element can spare for this class depends on everything it carries, so the
    # accumulation covers every circulating load, not only the class under test.
    carrying = sorted(
        (n for n in design.nodes.values() if n.kind in LOAD_KINDS and n.id in state.circulating),
        key=lambda n: n.id,
    )
    if not carrying:
        return unrun(a.id, mode, "no loads are circulating")
    totals, gaps = accumulate(design, state, carrying, "flow")
    missing += gaps

    ratings: dict[str, float] = {}
    for nid, carried in totals.items():
        node = design.nodes[nid]
        if node.kind in LOAD_KINDS or carried <= 0.0:
            continue
        rating = node.get("rating_lpm")
        if rating is None:
            missing.append(f"{nid}.rating_lpm")
        else:
            ratings[nid] = float(rating)
    if missing:
        return unrun(
            a.id, mode, f"{len(set(missing))} inputs are null", tuple(sorted(set(missing)))
        )

    offending: list[str] = []
    worst = 0.0
    for load in loads:
        if required[load.id] <= 0.0:  # a demand factor of 0: nothing to deliver, nothing short
            continue
        supply = _deliverable(
            _elements(design, legs(design, state, load.id, outward=False), outward=False),
            totals,
            ratings,
        )
        back = _deliverable(
            _elements(design, legs(design, state, load.id, outward=True), outward=True),
            totals,
            ratings,
        )
        available = required[load.id] * min(supply, back)
        shortfall = (available - required[load.id]) / required[load.id]
        worst = min(worst, shortfall)
        if shortfall < -tolerance:
            offending.append(
                f"{load.id} {required[load.id]:.0f} L/min required, "
                f"{available:.0f} L/min available ({shortfall:+.0%})"
            )

    subjects = tuple(n.id for n in loads)
    if offending:
        return Result(
            a.id,
            mode,
            Status.FAIL,
            f"{len(offending)}/{len(loads)} {cls} loads outside {tolerance:.0%} of required flow; "
            f"{METHOD}",
            subjects,
            tuple(offending),
        )
    return Result(
        a.id,
        mode,
        Status.PASS,
        f"{len(loads)} {cls} loads within {tolerance:.0%} of their required flow, "
        f"worst {worst:.0%}; {METHOD}",
        subjects,
    )
