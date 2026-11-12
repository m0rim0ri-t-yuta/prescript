"""Run every assertion in every mode it names and collect results."""

from __future__ import annotations

from dataclasses import replace

from prescript.checks import PLANNED, REGISTRY
from prescript.ir import META_MODE, STATIC_MODE, Assertion, Design
from prescript.modes import ModeState, resolve
from prescript.result import Result, Status, unrun


def _apply_severity(a: Assertion, r: Result) -> Result:
    if a.severity == "warn" and r.status is Status.FAIL:
        return replace(r, status=Status.WARN)
    return r


def _coverage(a: Assertion, results: list[Result]) -> Result:
    cells = [r for r in results if r.mode != META_MODE]
    if not cells:
        return unrun(a.id, META_MODE, "nothing to cover")
    ran = [r for r in cells if r.status is not Status.UNRUN]
    gaps = tuple(f"{r.assertion}@{r.mode}" for r in cells if r.status is Status.UNRUN)
    pct = 100.0 * len(ran) / len(cells)
    detail = f"{len(ran)}/{len(cells)} assertion x mode cells ran ({pct:.0f}%)"
    if gaps:
        return Result(a.id, META_MODE, Status.FAIL, detail, offending=gaps)
    return Result(a.id, META_MODE, Status.PASS, detail)


def run(design: Design) -> list[Result]:
    states: dict[str, ModeState] = {}
    results: list[Result] = []
    meta: list[Assertion] = []

    for a in design.assertions:
        if a.check == "coverage":
            meta.append(a)
            continue
        routine = REGISTRY.get(a.check)
        for mode in a.modes:
            if routine is None:
                why = "not implemented" if a.check in PLANNED else f"unknown check '{a.check}'"
                results.append(unrun(a.id, mode, why))
                continue
            if mode == STATIC_MODE:
                state = None
            else:
                if mode not in states:
                    states[mode] = resolve(design, design.modes[mode])
                state = states[mode]
            results.append(_apply_severity(a, routine(design, state, a)))

    for a in meta:
        results.append(_apply_severity(a, _coverage(a, results)))
    return results
