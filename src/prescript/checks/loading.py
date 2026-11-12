"""loading: equipment throughput vs rating in each mode.

args:
  kind:   one kind or a list (e.g. ups, [transformer, bus, ups, panel, rack_pdu])
  limit:  maximum loading as a fraction of rating (1.0 = 100 %, 0.8 = continuous-duty 80 %)
  basis:  kva | amps (optional; default per element: rating_kva -> kva, else rating_a -> amps)
  pf:     power factor for kW -> kVA / A when the element has no `pf` attribute

kVA = kW / pf.  A = kW / (sqrt(3) x voltage_kv x pf).  Flow method: prescript.flow.
"""

from __future__ import annotations

import math
from typing import Any

from prescript import flow
from prescript.ir import Assertion, Design, Node
from prescript.modes import ModeState
from prescript.result import Result, Status, unrun


def _loading(
    node: Node, kw: float, basis: str | None, pf_arg: Any
) -> tuple[float, str] | list[str]:
    """Return (fraction of rating, description) or the list of missing fields."""
    pf = node.get("pf") if node.get("pf") is not None else pf_arg
    use = basis or (
        "kva" if "rating_kva" in node.attrs else "amps" if "rating_a" in node.attrs else None
    )
    if use is None:
        return [f"{node.id}.rating_kva|rating_a"]
    needed: dict[str, Any] = {"pf": pf}
    if use == "kva":
        needed["rating_kva"] = node.get("rating_kva")
    else:
        needed["rating_a"] = node.get("rating_a")
        needed["voltage_kv"] = node.get("voltage_kv")
    gaps = [f"{node.id}.{k}" for k, v in needed.items() if v is None]
    if gaps:
        return gaps
    if use == "kva":
        value, rating, unit = kw / float(pf), float(node.attrs["rating_kva"]), "kVA"
    else:
        value = kw / (math.sqrt(3) * float(node.attrs["voltage_kv"]) * float(pf))
        rating, unit = float(node.attrs["rating_a"]), "A"
    return value / rating, f"{value:.0f}/{rating:.0f} {unit}"


def loading(design: Design, state: ModeState | None, a: Assertion) -> Result:
    if state is None:
        return unrun(a.id, "static", "loading needs an operating mode")
    kinds = a.args.get("kind", [])
    kinds = [kinds] if isinstance(kinds, str) else list(kinds)
    limit = a.args.get("limit")
    if limit is None:
        return unrun(a.id, state.mode, "loading needs args.limit", (f"{a.id}.args.limit",))
    basis = a.args.get("basis")
    basis = {"kva": "kva", "amps": "amps", None: None}.get(basis, basis)
    if basis not in ("kva", "amps", None):
        return unrun(a.id, state.mode, f"unknown basis '{basis}'")

    elements = sorted(design.nodes_of(kinds), key=lambda n: n.id)
    if not elements:
        return unrun(a.id, state.mode, f"no elements of kind {kinds}")

    f = flow.compute(design, state, design.modes[state.mode].demand)
    missing: list[str] = list(f.missing)
    over: list[str] = []
    worst: tuple[float, str] | None = None
    for node in elements:
        res = _loading(node, f.node_kw.get(node.id, 0.0), basis, a.args.get("pf"))
        if isinstance(res, list):
            missing += res
            continue
        frac, desc = res
        if worst is None or frac > worst[0]:
            worst = (frac, f"{node.id} {frac:.0%} ({desc})")
        if frac > float(limit) + 1e-9:
            over.append(f"{node.id} {frac:.0%} > {float(limit):.0%} ({desc})")

    subjects = tuple(n.id for n in elements)
    method = f"{flow.METHOD}, limit {float(limit):.0%}"
    if over:
        return Result(
            a.id,
            state.mode,
            Status.FAIL,
            f"{len(over)} over limit; {method}",
            subjects,
            tuple(over),
            tuple(sorted(set(missing))),
        )
    if missing:
        return unrun(
            a.id,
            state.mode,
            f"rating or demand data missing; {method}",
            tuple(sorted(set(missing))),
        )
    peak = worst[1] if worst else "no load"
    return Result(a.id, state.mode, Status.PASS, f"max {peak}; {method}", subjects)
