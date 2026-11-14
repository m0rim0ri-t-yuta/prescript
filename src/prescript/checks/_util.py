"""Shared helpers for the assertion routines.

`accumulate` is the one piece of arithmetic every sizing check builds on. It walks the closed loop
of each load: up the supply side to the CDU that drives it, and down the return side back to that
same CDU. The CDU is where the loop is cut, so no element is charged twice, and at every branch the
quantity is split by the edge `share`.
"""

from __future__ import annotations

import re

from prescript.ir import LOAD_KINDS, SOURCE_KINDS, Design, Edge, Node
from prescript.modes import ModeState

Basis = str  # "flow" (L/min) or "heat" (kW)

RATING_OF: dict[str, str] = {"flow": "rating_lpm", "heat": "rating_kw"}
UNIT_OF: dict[str, str] = {"flow": "L/min", "heat": "kW"}


def side_of(node_id: str, sides: list[str]) -> str | None:
    """Return the side tag carried by an id as a whole `-X` segment (e.g. MAN-A-01 -> A)."""
    for side in sides:
        if re.search(rf"(^|-){re.escape(side)}(-|$)", node_id):
            return side
    return None


def node_side(node: Node, sides: list[str]) -> str | None:
    declared = node.get("side")
    if isinstance(declared, str) and declared in sides:
        return declared
    return side_of(node.id, sides)


def targets(design: Design, cls: str) -> list[Node]:
    return sorted(design.loads_of_class(cls), key=lambda n: n.id)


def load_quantity(
    design: Design, state: ModeState, load: Node, basis: Basis
) -> tuple[float | None, list[str]]:
    """Heat (kW) or required flow (L/min) a load draws in this mode, plus the fields that are null.

    Flow follows the steady-state sensible-heat balance Q = V * rho * cp * dT.
    """
    heat = load.get("heat_kw")
    if heat is None:
        return None, [f"{load.id}.heat_kw"]
    factor = state.demand_factor(load.get("class"))
    if basis == "heat":
        return float(heat) * factor, []

    missing: list[str] = []
    raw_delta = load.get("delta_t_k")
    delta_t = float(raw_delta) if raw_delta is not None and float(raw_delta) > 0 else None
    if delta_t is None:
        missing.append(f"{load.id}.delta_t_k")
    fluid = design.fluid_of(load)
    volumetric = fluid.volumetric_heat_kj_lk() if fluid is not None else None
    if fluid is None:
        missing.append(f"{load.id}.fluid")
    elif volumetric is None:
        missing.append(f"fluid {fluid.name}.cp_kj_kgk/density_kg_l")
    if delta_t is None or volumetric is None:
        return None, missing
    return float(heat) * factor * 60.0 / (volumetric * delta_t), []


def _split(edges: list[Edge], neighbours: list[str], path: frozenset[str]) -> list[float]:
    """Normalised share of the quantity arriving at this node for each branch; 0.0 to skip."""
    weights = [
        0.0 if n in path else (1.0 if e.share is None else float(e.share))
        for e, n in zip(edges, neighbours, strict=True)
    ]
    total = sum(weights)
    if total <= 0:
        return [0.0] * len(edges)
    return [w / total for w in weights]


def _charge_supply(
    design: Design,
    state: ModeState,
    node_id: str,
    qty: float,
    totals: dict[str, float],
    path: frozenset[str],
) -> None:
    """Walk up the supply side, charging each element, and stop at the CDU that drives the loop."""
    feeds = [e for e in state.feeds(design, node_id) if design.nodes[e.src].kind not in LOAD_KINDS]
    sources = [e.src for e in feeds]
    for edge, fraction in zip(feeds, _split(feeds, sources, path), strict=True):
        if fraction == 0.0:
            continue
        totals[edge.src] = totals.get(edge.src, 0.0) + qty * fraction
        if design.nodes[edge.src].kind in SOURCE_KINDS:
            continue
        _charge_supply(design, state, edge.src, qty * fraction, totals, path | {edge.src})


def _charge_return(
    design: Design,
    state: ModeState,
    node_id: str,
    qty: float,
    totals: dict[str, float],
    path: frozenset[str],
) -> None:
    """Walk down the return side. The supply walk already charged the CDU, so stop before it."""
    outlets = [
        e for e in state.outlets(design, node_id) if design.nodes[e.dst].kind not in LOAD_KINDS
    ]
    destinations = [e.dst for e in outlets]
    for edge, fraction in zip(outlets, _split(outlets, destinations, path), strict=True):
        if fraction == 0.0 or design.nodes[edge.dst].kind in SOURCE_KINDS:
            continue
        totals[edge.dst] = totals.get(edge.dst, 0.0) + qty * fraction
        _charge_return(design, state, edge.dst, qty * fraction, totals, path | {edge.dst})


def accumulate(
    design: Design, state: ModeState, loads: list[Node], basis: Basis
) -> tuple[dict[str, float], list[str]]:
    """Quantity carried by every element of the loops that serve `loads`, and any null inputs."""
    totals: dict[str, float] = {}
    missing: list[str] = []
    for load in loads:
        qty, gaps = load_quantity(design, state, load, basis)
        missing += gaps
        if qty is None:
            continue
        totals[load.id] = totals.get(load.id, 0.0) + qty
        start = frozenset({load.id})
        _charge_supply(design, state, load.id, qty, totals, start)
        _charge_return(design, state, load.id, qty, totals, start)
    return totals, missing


def upstream(design: Design, state: ModeState, node_id: str) -> set[str]:
    """Every element that feeds `node_id` in this mode, up to and including the driving CDU."""
    seen: set[str] = set()
    stack = [node_id]
    while stack:
        current = stack.pop()
        for edge in state.feeds(design, current):
            if edge.src in seen or design.nodes[edge.src].kind in LOAD_KINDS:
                continue
            seen.add(edge.src)
            if design.nodes[edge.src].kind not in SOURCE_KINDS:
                stack.append(edge.src)
    return seen
