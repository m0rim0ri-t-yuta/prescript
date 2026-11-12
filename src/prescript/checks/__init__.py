"""Assertion routines. One module per routine; register it in REGISTRY.

A routine is a pure function `(design, state, assertion) -> Result`. `state` is None for routines
that run in the `static` pseudo-mode. `coverage` is not here: it runs over the other results and
lives in prescript.engine.
"""

from __future__ import annotations

from collections.abc import Callable

from prescript.checks.completeness import completeness
from prescript.checks.dual_path import dual_path
from prescript.checks.path_exists import path_exists
from prescript.ir import Assertion, Design
from prescript.modes import ModeState
from prescript.result import Result

Check = Callable[[Design, ModeState | None, Assertion], Result]

REGISTRY: dict[str, Check] = {
    "completeness": completeness,
    "dual_path": dual_path,
    "path_exists": path_exists,
}

# Named in the reference design but not built yet. They return UNRUN, never PASS.
PLANNED: frozenset[str] = frozenset(
    {
        "n_minus_1",
        "diverse_upstream",
        "standby_diverse",
        "loading",
        "generator_margin",
        "breaker_duty",
        "time_margin",
        "consistency",
    }
)
