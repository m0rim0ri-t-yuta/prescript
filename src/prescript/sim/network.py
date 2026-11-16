"""Hydraulic network built from a netlist, solved quasi-steadily (Phase 2, #45).

Every netlist node becomes an element between two junctions, `<id>:in` and `<id>:out`; every
netlist edge joins the source's outlet to the destination's inlet, through its valve when it has
one. An edge without a valve is a plain connection, so its two ends are the same junction.

Element laws, `dp = p(in) - p(out)` as a function of the flow `q` (L/min, positive in -> out):

- header: Darcy-Weisbach with Swamee-Jain, the same function `pressure_drop` (C-09) uses;
- CDU exchanger, manifold, rack, rear door: the rated drop scaled with `q^2`, as in C-09;
- valve: `100 * SG * (0.06 * q / (x * Kv))^2` kPa at stroke `x` (linear characteristic); shut, it
  carries no flow;
- pump: a quadratic curve through the shut-off head and the rated point,
  `H(q, s) = s^2 * shutoff_kpa - (shutoff_kpa - rating_kpa) * (q / rating_lpm)^2` at speed `s`
  (affinity laws). A stopped pump carries no flow: a discharge check valve is assumed, so it cannot
  run backwards either.

Pressure needs a reference. A closed loop has one point of no pressure change, the expansion tank:
the first CDU in netlist order with `fill_kpa` (gauge, at the CDU inlet) pins its loop. A loop with
no such CDU has flows but no absolute pressure, and anything judged on pressure is `UNRUN` there.

The network is solved by Newton's method on junction pressures and element flows. A small linear
term (`_LEAK`, kPa per L/min) keeps the Jacobian regular where a branch carries no flow; it adds
0.01 kPa at 1000 L/min. Fluid inertia is neglected (quasi-steady): the flows follow the valves and
pumps instantly, so pressure waves (water hammer) are not represented here — see `scoreboard`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from prescript.checks.pressure_drop import _Inputs, _pipe_kpa, _rated_kpa, _valve_kpa
from prescript.ir import Design, Device, Fluid, Node

METHOD = (
    "quasi-steady network solve (Newton): darcy-weisbach (swamee-jain) headers, Q^2 rated drops, "
    "Kv valves with a linear stroke, quadratic pump curves through shut-off and rated head, "
    "check valves on stopped pumps, one expansion tank per loop"
)

_LEAK = 1e-5  # kPa per L/min of regularising linear drop on every element
_PIPE_H = 1.0  # L/min, step of the numerical derivative of the pipe law
_RATED = {"cdu", "manifold", "rack", "rdhx"}


class NetworkError(ValueError):
    """The netlist cannot be turned into a network (a null the solver needs, an unknown fluid)."""


@dataclass(frozen=True)
class Element:
    id: str
    kind: str  # "pump" | "pipe" | "rated" | "valve"
    a: int  # junction at the inlet
    b: int  # junction at the outlet
    node: Node | None = None
    valve: Device | None = None


@dataclass
class Network:
    """The netlist as junctions and elements. Built once; solved for every operating point."""

    design: Design
    fluid: Fluid
    junctions: list[str]
    elements: list[Element]
    index: dict[str, int]  # element id -> position in `elements`
    tank: dict[int, float]  # junction -> gauge pressure fixed by an expansion tank, kPa
    missing: tuple[str, ...]  # nulls the hydraulic laws needed
    _pump_k: dict[str, tuple[float, float]] = field(default_factory=dict)  # id -> (shutoff, k)

    def element(self, element_id: str) -> Element:
        return self.elements[self.index[element_id]]


@dataclass(frozen=True)
class Operating:
    """What the actuators are doing: valve strokes (0..1), pump speeds (0..1), stopped CDUs."""

    valve: dict[str, float]
    speed: dict[str, float]


@dataclass(frozen=True)
class Solution:
    flow: dict[str, float]  # element id -> L/min, positive in -> out
    pressure: NDArray[np.float64]  # per junction, kPa gauge; NaN where the loop has no tank
    pressurised: NDArray[np.bool_]
    converged: bool


def _find(parent: dict[str, str], key: str) -> str:
    while parent[key] != key:
        parent[key] = parent[parent[key]]
        key = parent[key]
    return key


def build(design: Design) -> Network:
    fluids = {str(n.get("fluid")) for n in design.nodes.values() if n.get("fluid") is not None}
    if len(fluids) != 1 or next(iter(fluids)) not in design.fluids:
        raise NetworkError(f"the network needs exactly one known coolant, found {sorted(fluids)}")
    fluid = design.fluids[next(iter(fluids))]

    parent: dict[str, str] = {}
    for nid in design.nodes:
        for end in (f"{nid}:in", f"{nid}:out"):
            parent[end] = end
    for edge in design.edges:
        if edge.via is None:
            up, down = _find(parent, f"{edge.src}:out"), _find(parent, f"{edge.dst}:in")
            parent[down] = up
    roots: dict[str, int] = {}
    junctions: list[str] = []

    def junction(key: str) -> int:
        root = _find(parent, key)
        if root not in roots:
            roots[root] = len(junctions)
            junctions.append(root)
        return roots[root]

    inputs = _Inputs()
    elements: list[Element] = []
    pump_k: dict[str, tuple[float, float]] = {}
    for node in design.nodes.values():
        a, b = junction(f"{node.id}:in"), junction(f"{node.id}:out")
        if node.kind == "pump":
            shutoff = inputs.number(node.id, node.attrs, "shutoff_kpa")
            rated = inputs.number(node.id, node.attrs, "rating_kpa")
            at = inputs.number(node.id, node.attrs, "rating_lpm")
            if shutoff is not None and rated is not None and at:
                if shutoff <= rated:
                    raise NetworkError(f"{node.id}: shutoff_kpa must exceed rating_kpa")
                pump_k[node.id] = (shutoff, (shutoff - rated) / at**2)
            elements.append(Element(node.id, "pump", a, b, node=node))
        elif node.kind == "header":
            for key in ("dn_mm", "length_m", "roughness_mm", "k_fittings"):
                inputs.number(node.id, node.attrs, key)
            elements.append(Element(node.id, "pipe", a, b, node=node))
        elif node.kind in _RATED:
            inputs.number(node.id, node.attrs, "dp_kpa")
            inputs.number(node.id, node.attrs, "dp_lpm")
            elements.append(Element(node.id, "rated", a, b, node=node))
        else:
            raise NetworkError(f"{node.id}: no hydraulic law for kind '{node.kind}'")
    for edge in design.edges:
        if edge.via is not None:
            inputs.number(edge.via.id, edge.via.attrs, "kv_m3h")
            a, b = junction(f"{edge.src}:out"), junction(f"{edge.dst}:in")
            elements.append(Element(edge.via.id, "valve", a, b, valve=edge.via))

    tank: dict[int, float] = {}
    for cdu in design.nodes_of("cdu"):
        fill = cdu.get("fill_kpa")
        if fill is not None:
            tank[junction(f"{cdu.id}:in")] = float(fill)
    return Network(
        design=design,
        fluid=fluid,
        junctions=junctions,
        elements=elements,
        index={e.id: i for i, e in enumerate(elements)},
        tank=tank,
        missing=tuple(sorted(inputs.missing)),
        _pump_k=pump_k,
    )


def _drop(net: Network, e: Element, q: float, op: Operating) -> tuple[float, float]:
    """`p(a) - p(b)` the element needs to pass `q`, and its derivative in `q`."""
    inputs = _Inputs()
    sign = 1.0 if q >= 0.0 else -1.0
    mag = abs(q)
    if e.kind == "pump":
        shutoff, k = net._pump_k[e.id]
        s = op.speed.get(e.id, 0.0)
        return -(s * s * shutoff) + k * q * mag + _LEAK * q, 2.0 * k * mag + _LEAK
    if e.kind == "pipe":
        assert e.node is not None
        f = _pipe_kpa(e.node, mag, net.fluid, inputs)
        f_hi = _pipe_kpa(e.node, mag + _PIPE_H, net.fluid, inputs)
        f_lo = _pipe_kpa(e.node, max(mag - _PIPE_H, 0.0), net.fluid, inputs)
        slope = (f_hi - f_lo) / (mag + _PIPE_H - max(mag - _PIPE_H, 0.0))
        return sign * f + _LEAK * q, slope + _LEAK
    if e.kind == "rated":
        assert e.node is not None
        r = _rated_kpa(e.node, 1.0, inputs)  # kPa at 1 L/min, i.e. the Q^2 coefficient
        return r * q * mag + _LEAK * q, 2.0 * r * mag + _LEAK
    assert e.valve is not None
    x = op.valve.get(e.id, 1.0)
    r = _valve_kpa(e.valve, 1.0, net.fluid, inputs) / (x * x)
    return r * q * mag + _LEAK * q, 2.0 * r * mag + _LEAK


def _conducts(net: Network, e: Element, op: Operating) -> bool:
    if e.kind == "valve":
        return op.valve.get(e.id, 1.0) > 1e-6
    if e.kind == "pump":
        return op.speed.get(e.id, 0.0) > 1e-6 and e.id in net._pump_k
    return True


def _components(net: Network, live: list[bool]) -> list[int]:
    parent = list(range(len(net.junctions)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for e, on in zip(net.elements, live, strict=True):
        if on:
            parent[find(e.a)] = find(e.b)
    return [find(i) for i in range(len(net.junctions))]


def solve(net: Network, op: Operating, guess: Solution | None = None) -> Solution:
    """Flows and pressures at this operating point. Raises NetworkError on missing data."""
    if net.missing:
        raise NetworkError(f"null values the network needs: {', '.join(net.missing)}")
    blocked: set[str] = set()
    for _ in range(len(net.elements) + 1):
        sol = _newton(net, op, blocked, guess)
        backwards = {
            e.id for e in net.elements if e.kind == "pump" and sol.flow.get(e.id, 0.0) < -1e-3
        }
        if not backwards - blocked:
            return sol
        blocked |= backwards  # the check valve shuts: solve again without that pump
        guess = sol
    return sol


def _newton(net: Network, op: Operating, blocked: set[str], guess: Solution | None) -> Solution:
    m, n = len(net.elements), len(net.junctions)
    live = [_conducts(net, e, op) and e.id not in blocked for e in net.elements]
    comp = _components(net, live)
    pinned: dict[int, float] = {}
    pressurised = np.zeros(n, dtype=bool)
    for root in set(comp):
        members = [j for j in range(n) if comp[j] == root]
        tanks = [j for j in sorted(net.tank) if comp[j] == root]
        if tanks:
            pinned[tanks[0]] = net.tank[tanks[0]]
            pressurised[members] = True
        else:
            pinned[members[0]] = 0.0  # pressure only up to a constant here
    free = [j for j in range(n) if j not in pinned]
    col = {j: i for i, j in enumerate(free)}

    q = np.zeros(m)
    p = np.zeros(n)
    for j, v in pinned.items():
        p[j] = v
    if guess is not None:
        q = np.array([guess.flow.get(e.id, 0.0) for e in net.elements])
        warm = np.nan_to_num(guess.pressure)
        for j in free:
            p[j] = warm[j]
    for i, on in enumerate(live):
        if not on:
            q[i] = 0.0

    size = len(free) + m
    converged = False
    for _ in range(100):
        res = np.zeros(size)
        jac = np.zeros((size, size))
        for i, e in enumerate(net.elements):
            row = len(free) + i
            if not live[i]:
                res[row] = q[i]
                jac[row, row] = 1.0
                continue
            f, df = _drop(net, e, float(q[i]), op)
            res[row] = p[e.a] - p[e.b] - f
            if e.a in col:
                jac[row, col[e.a]] += 1.0
            if e.b in col:
                jac[row, col[e.b]] -= 1.0
            jac[row, row] = -df
            # continuity: what arrives at a junction leaves it
            if e.b in col:
                res[col[e.b]] += q[i]
                jac[col[e.b], row] += 1.0
            if e.a in col:
                res[col[e.a]] -= q[i]
                jac[col[e.a], row] -= 1.0
        if np.max(np.abs(res)) < 1e-6:
            converged = True
            break
        step = np.linalg.solve(jac, -res)
        scale = 1.0
        base = float(np.max(np.abs(res)))
        for _ in range(30):  # backtracking keeps Newton honest on the pump curves
            trial_p, trial_q = p.copy(), q + scale * step[len(free) :]
            for j, c in col.items():
                trial_p[j] = p[j] + scale * step[c]
            if _residual(net, op, live, col, trial_p, trial_q) < base or scale < 1e-3:
                break
            scale *= 0.5
        p, q = trial_p, trial_q
    pressure = np.where(pressurised, p, np.nan)
    return Solution(
        flow={e.id: float(q[i]) for i, e in enumerate(net.elements)},
        pressure=pressure,
        pressurised=pressurised,
        converged=converged,
    )


def _residual(
    net: Network,
    op: Operating,
    live: list[bool],
    col: dict[int, int],
    p: NDArray[np.float64],
    q: NDArray[np.float64],
) -> float:
    worst = 0.0
    balance = np.zeros(len(net.junctions))
    for i, e in enumerate(net.elements):
        if not live[i]:
            worst = max(worst, abs(float(q[i])))
            continue
        f, _ = _drop(net, e, float(q[i]), op)
        worst = max(worst, abs(float(p[e.a] - p[e.b]) - f))
        balance[e.b] += q[i]
        balance[e.a] -= q[i]
    for j in col:
        worst = max(worst, abs(float(balance[j])))
    return worst
