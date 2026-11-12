"""completeness: every element of the named kinds carries non-null ratings.

A rating field is any attribute whose name starts with `rating_` (plus `break_ka` for breakers).
This is how the design tells you which other checks will come back UNRUN.
"""

from __future__ import annotations

from typing import Any

from prescript.ir import Assertion, Design
from prescript.modes import ModeState
from prescript.result import Result, Status


def _missing(elem_id: str, attrs: dict[str, Any], extra: tuple[str, ...]) -> list[str]:
    keys = [k for k in attrs if k.startswith("rating_")] + [k for k in extra if k in attrs]
    if not keys:
        return [f"{elem_id}.rating_*"]
    return [f"{elem_id}.{k}" for k in keys if attrs[k] is None]


def completeness(design: Design, state: ModeState | None, a: Assertion) -> Result:
    kinds = {str(k) for k in a.args.get("kinds", [])}
    subjects: list[str] = []
    missing: list[str] = []
    for node in sorted(design.nodes.values(), key=lambda n: n.id):
        if node.kind in kinds:
            subjects.append(node.id)
            missing += _missing(node.id, node.attrs, ())
    for dev in sorted(design.devices().values(), key=lambda d: d.id):
        if dev.kind in kinds:
            subjects.append(dev.id)
            missing += _missing(dev.id, dev.attrs, ("break_ka",))

    if not subjects:
        return Result(a.id, "static", Status.UNRUN, f"no elements of kinds {sorted(kinds)}")
    if missing:
        return Result(
            a.id,
            "static",
            Status.FAIL,
            f"{len(missing)} rating fields are null across {len(subjects)} elements",
            tuple(subjects),
            tuple(missing),
        )
    return Result(
        a.id, "static", Status.PASS, f"{len(subjects)} elements fully rated", tuple(subjects)
    )
