"""Assertion routines. One module per routine; register it in REGISTRY.

A routine is a pure function `(design, state, assertion) -> Result`. `state` is None for routines
that run in the `static` pseudo-mode. `coverage` is not here: it runs over the other results and
lives in prescript.engine.
"""

from __future__ import annotations

from collections.abc import Callable

from prescript.checks.balance import balance
from prescript.checks.completeness import completeness
from prescript.checks.consistency import consistency
from prescript.checks.dual_path import dual_path
from prescript.checks.inlet_temp import inlet_temp
from prescript.checks.loading import loading
from prescript.checks.loop_closed import loop_closed
from prescript.checks.n_minus_1 import n_minus_1
from prescript.checks.pressure_drop import pressure_drop
from prescript.checks.return_temp import return_temp
from prescript.checks.ride_through import ride_through
from prescript.ir import Assertion, Design
from prescript.modes import ModeState
from prescript.result import Result

Check = Callable[[Design, ModeState | None, Assertion], Result]

REGISTRY: dict[str, Check] = {
    "balance": balance,
    "completeness": completeness,
    "consistency": consistency,
    "dual_path": dual_path,
    "inlet_temp": inlet_temp,
    "loading": loading,
    "loop_closed": loop_closed,
    "n_minus_1": n_minus_1,
    "pressure_drop": pressure_drop,
    "return_temp": return_temp,
    "ride_through": ride_through,
}

# Named in the reference design but not built yet. They return UNRUN, never PASS.
PLANNED: frozenset[str] = frozenset(
    {
        "leak_isolation",
    }
)
