"""consistency: the elaborated netlist still agrees with the spec table it was built from.

A block expands into many nodes, so one parameter edit moves eight racks at once and nothing in
the design says it was not meant to. The `spec:` tables are the sheets the design came from,
transcribed beside it; this routine compares them with the elaborated design, field by field, in
the `static` pseudo-mode.

It compares, it does not convert: a row's field name is the attribute name on the node, and both
sides are read in the unit that name carries. A value that is `null` on either side is not a
disagreement but an unanswered question, so it is reported in `missing`, and a row the table names
but the netlist does not have is a disagreement, not an absence. A proven disagreement is still a
FAIL when some other cell could not be compared — the cells that could not are listed with it.
"""

from __future__ import annotations

import math
from typing import Any

from prescript.ir import STATIC_MODE, Assertion, Design
from prescript.modes import ModeState
from prescript.result import Result, Status, unrun

METHOD = "method: field-by-field against the transcribed spec table, no unit conversion"


def _same(netlist: Any, spec: Any) -> bool:
    """Numbers compare as numbers, everything else as the text the netlist writes."""
    if isinstance(netlist, bool) or isinstance(spec, bool):
        return bool(netlist) is bool(spec)
    if isinstance(netlist, int | float) and isinstance(spec, int | float):
        return math.isclose(float(netlist), float(spec), rel_tol=1e-9)
    return str(netlist) == str(spec)


def consistency(design: Design, state: ModeState | None, a: Assertion) -> Result:
    against = str(a.args.get("against", ""))
    fields = [str(f) for f in a.args.get("fields", [])]
    if not against:
        return unrun(a.id, STATIC_MODE, "consistency needs a table to compare against")
    if not fields:
        return unrun(a.id, STATIC_MODE, f"consistency needs the fields to compare in {against}")
    table = design.spec.get(against)
    if table is None:
        known = ", ".join(sorted(design.spec)) or "none"
        return unrun(
            a.id,
            STATIC_MODE,
            f"no spec table '{against}' (this netlist has: {known})",
            (f"spec.{against}",),
        )

    missing: list[str] = []
    offending: list[str] = []
    for row_id in sorted(table.rows):
        row = table.rows[row_id]
        node = design.nodes.get(row_id)
        if node is None:
            offending.append(f"{row_id}: in {against}, not in the netlist")
            continue
        for field in fields:
            want, have = row.get(field), node.get(field)
            if want is None:
                missing.append(f"spec {against}.{row_id}.{field}")
            if have is None:
                missing.append(f"{row_id}.{field}")
            if want is None or have is None:
                continue
            if not _same(have, want):
                offending.append(f"{row_id}.{field}: netlist {have}, {against} {want}")

    subjects = tuple(sorted(table.rows))
    compared = ", ".join(fields)
    if offending:
        return Result(
            a.id,
            STATIC_MODE,
            Status.FAIL,
            f"{len(offending)} disagreements with {against} across {len(subjects)} rows; {METHOD}",
            subjects,
            tuple(offending),
            tuple(sorted(set(missing))),
        )
    if missing:
        unique = tuple(sorted(set(missing)))
        return unrun(a.id, STATIC_MODE, f"{len(unique)} cells cannot be compared", unique)
    return Result(
        a.id,
        STATIC_MODE,
        Status.PASS,
        f"{len(subjects)} rows of {against} match the netlist on {compared}; {METHOD}",
        subjects,
    )
