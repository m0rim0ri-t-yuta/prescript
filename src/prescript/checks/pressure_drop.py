"""pressure_drop: the pump on every loop has the head to push the loop's design flow round it.

`loading` and `balance` say how much has to flow where. This routine asks whether it can: it adds
up the pressure drop around each load's loop at the flows `accumulate` gives, and compares it with
the rated head of the pump on that loop.

The method is a 1-D screening, named in every result:

- headers are pipe: Darcy-Weisbach, `dP = (f * L/D + sum K) * rho * v^2 / 2`, with the friction
  factor from Swamee-Jain (64/Re below Re 2300). The whole header flow is taken over the whole
  header length, which over-states the drop at the far end of a distribution main;
- equipment with a rated drop (`dp_kpa` at `dp_lpm`: CDU exchanger, manifold, rack, rear door)
  scales with the square of flow;
- a valve drops `100 * SG * (Q / Kv)^2` kPa, with Q in m^3/h;
- the pump delivers its rated head (`rating_kpa`) at any flow — one point, not its curve.

A load's loop is one of its supply legs (which carries the pump and the CDU), the load itself, and
the worst of its return legs; the index circuit is the worst of those. It is single phase, steady
state, and does not solve the network: parallel paths are not balanced against each other.
"""

from __future__ import annotations

import math

from prescript.checks._util import Leg, accumulate, legs, load_quantity
from prescript.ir import LOAD_KINDS, SOURCE_KINDS, Assertion, Design, Device, Edge, Fluid, Node
from prescript.modes import ModeState
from prescript.result import Result, Status, unrun

METHOD = (
    "method: darcy-weisbach (swamee-jain) headers, Q^2 rated drops, Kv valves; "
    "index circuit vs pump rated head, single phase"
)
SUPPORTED = {"darcy_weisbach"}
_RATED_DROP = {"cdu", "manifold", "rack", "rdhx"}
_PIPE = {"header"}
_PIPE_FIELDS = ("dn_mm", "length_m", "roughness_mm", "k_fittings")


class _Inputs:
    """Collects the null fields a calculation touched, so the result can list every one."""

    def __init__(self) -> None:
        self.missing: set[str] = set()

    def number(self, owner: str, attrs: dict[str, object], key: str) -> float | None:
        value = attrs.get(key)
        if value is None:
            self.missing.add(f"{owner}.{key}")
            return None
        return float(value)  # type: ignore[arg-type]


def _pipe_kpa(node: Node, flow_lpm: float, fluid: Fluid, inputs: _Inputs) -> float:
    """Darcy-Weisbach with Swamee-Jain; the full flow over the full length."""
    dn, length, roughness, k = (inputs.number(node.id, node.attrs, f) for f in _PIPE_FIELDS)
    if fluid.density_kg_l is None:
        inputs.missing.add(f"fluid {fluid.name}.density_kg_l")
    if fluid.viscosity_mpas is None:
        inputs.missing.add(f"fluid {fluid.name}.viscosity_mpas")
    if (
        dn is None
        or length is None
        or roughness is None
        or k is None
        or fluid.density_kg_l is None
        or fluid.viscosity_mpas is None
        or dn <= 0.0
        or flow_lpm <= 0.0
    ):
        return 0.0
    diameter = dn / 1000.0
    rho = fluid.density_kg_l * 1000.0
    velocity = (flow_lpm / 60000.0) / (math.pi * diameter**2 / 4.0)
    reynolds = rho * velocity * diameter / (fluid.viscosity_mpas / 1000.0)
    if reynolds < 2300.0:
        friction = 64.0 / reynolds
    else:
        relative = roughness / 1000.0 / (3.7 * diameter)
        friction = 0.25 / math.log10(relative + 5.74 / reynolds**0.9) ** 2
    return (friction * length / diameter + k) * rho * velocity**2 / 2.0 / 1000.0


def _rated_kpa(node: Node, flow_lpm: float, inputs: _Inputs) -> float:
    dp = inputs.number(node.id, node.attrs, "dp_kpa")
    at = inputs.number(node.id, node.attrs, "dp_lpm")
    if dp is None or not at:
        return 0.0
    return dp * (flow_lpm / at) ** 2


def _valve_kpa(valve: Device, flow_lpm: float, fluid: Fluid, inputs: _Inputs) -> float:
    kv = inputs.number(valve.id, valve.attrs, "kv_m3h")
    gravity = fluid.density_kg_l  # relative to water at 1 kg/L
    if gravity is None:
        inputs.missing.add(f"fluid {fluid.name}.density_kg_l")
    if not kv or gravity is None:
        return 0.0
    return 100.0 * gravity * (flow_lpm * 0.06 / kv) ** 2


class _Loop:
    """Pressure drop of elements and valves at this mode's flows, for one fluid."""

    def __init__(
        self,
        design: Design,
        nodes: dict[str, float],
        edges: dict[int, float],
        fluid: Fluid,
        inputs: _Inputs,
    ) -> None:
        self.design, self.nodes, self.edges, self.fluid, self.inputs = (
            design,
            nodes,
            edges,
            fluid,
            inputs,
        )

    def node(self, node_id: str) -> float:
        node = self.design.nodes[node_id]
        flow = self.nodes.get(node_id, 0.0)
        if node.kind in _PIPE:
            return _pipe_kpa(node, flow, self.fluid, self.inputs)
        if node.kind in _RATED_DROP:
            return _rated_kpa(node, flow, self.inputs)
        return 0.0  # a pump adds head; it is not a loss

    def edge(self, edge: Edge) -> float:
        if edge.via is None:
            return 0.0
        return _valve_kpa(edge.via, self.edges.get(id(edge), 0.0), self.fluid, self.inputs)

    def supply(self, leg: Leg) -> tuple[float, list[Node]]:
        """Drop up a supply leg (CDU included) and the pumps on it."""
        _, edges = leg
        drop = sum(self.edge(e) + self.node(e.src) for e in edges)
        pumps = [self.design.nodes[e.src] for e in edges if self.design.nodes[e.src].kind == "pump"]
        return drop, pumps

    def back(self, leg: Leg) -> float:
        """Drop down a return leg, stopping before the CDU the supply side already counted."""
        _, edges = leg
        return sum(
            self.edge(e)
            + (0.0 if self.design.nodes[e.dst].kind in SOURCE_KINDS else self.node(e.dst))
            for e in edges
        )


def _edge_flows(
    design: Design, state: ModeState, loads: list[Node]
) -> tuple[dict[int, float], list[str]]:
    """Flow on every edge, from each load's legs with the same split `accumulate` uses."""
    flows: dict[int, float] = {}
    missing: list[str] = []
    for load in loads:
        qty, gaps = load_quantity(design, state, load, "flow")
        missing += gaps
        if qty is None:
            continue
        for outward in (False, True):
            for weight, edges in legs(design, state, load.id, outward=outward):
                for edge in edges:
                    flows[id(edge)] = flows.get(id(edge), 0.0) + qty * weight
    return flows, missing


def pressure_drop(design: Design, state: ModeState | None, a: Assertion) -> Result:
    mode = state.mode if state else "static"
    if state is None:
        return unrun(a.id, mode, "pressure_drop needs an operating mode")
    method = str(a.args.get("method", "darcy_weisbach"))
    if method not in SUPPORTED:
        return unrun(a.id, mode, f"unknown method '{method}'")
    limit = float(a.args.get("limit", 1.0))
    override = a.args.get("available_kpa")

    loads = sorted(
        (n for n in design.nodes.values() if n.kind in LOAD_KINDS and n.id in state.circulating),
        key=lambda n: n.id,
    )
    if not loads:
        return unrun(a.id, mode, "no loads are circulating")

    nodes, gaps = accumulate(design, state, loads, "flow")
    edges, more = _edge_flows(design, state, loads)
    inputs = _Inputs()
    inputs.missing.update(gaps + more)

    offending: list[str] = []
    worst = 0.0
    for load in loads:
        fluid = design.fluid_of(load)
        if fluid is None:
            inputs.missing.add(f"{load.id}.fluid")
            continue
        loop = _Loop(design, nodes, edges, fluid, inputs)
        own = loop.node(load.id)
        back = max(
            (loop.back(leg) for leg in legs(design, state, load.id, outward=True)), default=0.0
        )
        worst_here: tuple[float, float, float, str] | None = None
        for leg in legs(design, state, load.id, outward=False):
            drop, pumps = loop.supply(leg)
            if override is not None:
                head, via = float(override), "available_kpa"
            elif not pumps:
                inputs.missing.add(f"{load.id}: no pump on a supply leg")
                continue
            else:
                heads = [inputs.number(p.id, p.attrs, "rating_kpa") for p in pumps]
                if any(h is None for h in heads):
                    continue
                head, via = sum(h for h in heads if h is not None), "+".join(p.id for p in pumps)
            circuit = drop + own + back
            ratio = circuit / head if head > 0 else math.inf
            if worst_here is None or ratio > worst_here[0]:
                worst_here = (ratio, circuit, head, via)
        if worst_here is None:
            continue
        ratio, circuit, head, via = worst_here
        worst = max(worst, ratio)
        if ratio > limit:
            offending.append(f"{load.id} via {via}: {circuit:.0f}/{head:.0f} kPa ({ratio:.0%})")

    subjects = tuple(n.id for n in loads)
    if inputs.missing:
        missing = tuple(sorted(inputs.missing))
        return unrun(a.id, mode, f"{len(missing)} inputs are null", missing)
    if offending:
        return Result(
            a.id,
            mode,
            Status.FAIL,
            f"{len(offending)}/{len(loads)} loops exceed {limit:.0%} of the available head; "
            f"{METHOD}",
            subjects,
            tuple(offending),
        )
    return Result(
        a.id,
        mode,
        Status.PASS,
        f"{len(loads)} loops within the available head, worst {worst:.0%}; {METHOD}",
        subjects,
    )
