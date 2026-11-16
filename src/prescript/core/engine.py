"""Run every assertion in every mode it names and collect the results.

The domain supplies three things: its check routines by name, a function that builds the state of
one operating mode, and (optionally) post-checks that run over the other results, such as
coverage. The rules that make a result trustworthy live here, so every domain gets them:

- a check that is planned but not built, or unknown, is UNRUN in every mode it names;
- a mode whose state cannot be built (`Unsolvable`) makes every assertion in it UNRUN with the
  reason, and the rest of the matrix still fills in;
- a `warn` assertion reports WARN where it would FAIL, and nothing else changes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from prescript.core.spec import META_MODE, STATIC_MODE, AssertionSpec, DesignSpec
from prescript.result import Result, Status, unrun

# `(design, state, assertion) -> Result`; state is None in the static and meta pseudo-modes. The
# assertion is typed `Any` so that a routine can take the domain's own assertion class.
type Check[D, S] = Callable[[D, S | None, Any], Result]
# `(assertion, results so far) -> Result`; runs after every per-mode and pseudo-mode cell.
type PostCheck = Callable[[Any, list[Result]], Result]


class Unsolvable(Exception):
    """Raised by a domain's state function: this mode has no state, and here is why."""


def run[D: DesignSpec, S](
    design: D,
    registry: Mapping[str, Check[D, S]],
    state: Callable[[str], S],
    *,
    planned: frozenset[str] = frozenset(),
    post: Mapping[str, PostCheck] | None = None,
) -> list[Result]:
    """Results in assertion order, each assertion's modes in its own order; post-checks last.

    `state(mode)` is called at most once per mode, and only for a mode some routine runs in.
    """
    post = post or {}
    states: dict[str, S] = {}
    unsolvable: dict[str, str] = {}
    results: list[Result] = []
    deferred: list[AssertionSpec] = []

    for a in design.assertions:
        if a.check in post:
            deferred.append(a)
            continue
        routine = registry.get(a.check)
        for mode in a.modes:
            if routine is None:
                why = "not implemented" if a.check in planned else f"unknown check '{a.check}'"
                results.append(unrun(a.id, mode, why))
                continue
            if mode in (STATIC_MODE, META_MODE):
                results.append(_apply_severity(a, routine(design, None, a)))
                continue
            if mode not in design.modes:
                results.append(unrun(a.id, mode, f"unknown mode '{mode}'"))
                continue
            if mode not in states and mode not in unsolvable:
                try:
                    states[mode] = state(mode)
                except Unsolvable as exc:
                    unsolvable[mode] = str(exc)
            if mode in unsolvable:
                results.append(unrun(a.id, mode, unsolvable[mode]))
                continue
            results.append(_apply_severity(a, routine(design, states[mode], a)))

    for a in deferred:
        results.append(_apply_severity(a, post[a.check](a, results)))
    return results


def _apply_severity(a: AssertionSpec, r: Result) -> Result:
    if a.severity == "warn" and r.status is Status.FAIL:
        return replace(r, status=Status.WARN)
    return r
