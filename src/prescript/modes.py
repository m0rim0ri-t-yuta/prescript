"""Per-mode state resolution and circulation.

A mode overrides node and valve states and sets the operating conditions. From the resolved states
we compute two sets: what a running CDU can reach (`circulating`) and what can reach a running CDU
back (`draining`). A dead leg is in the first and not in the second, and carries no flow. This is
topology only — no pressure, no load flow.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from prescript.ir import SOURCE_KINDS, Design, Edge, Mode

# Node states that stop a node from circulating or from passing flow on.
_DEAD_STATES = {"off", "standby"}


@dataclass(frozen=True)
class ModeState:
    mode: str
    node_state: dict[str, str]
    device_state: dict[str, str]
    demand: dict[str, float]
    conditions: dict[str, float]
    circulating: frozenset[str] = field(default_factory=frozenset)
    draining: frozenset[str] = field(default_factory=frozenset)

    def conducts(self, edge: Edge) -> bool:
        """Can fluid cross this edge in this mode? A valve conducts when it is open."""
        return edge.via is None or self.device_state.get(edge.via.id, "open") == "open"

    def feeds(self, design: Design, node_id: str) -> list[Edge]:
        """Incoming edges that actually deliver cooling to `node_id` in this mode."""
        return [
            e for e in design.incoming(node_id) if e.src in self.circulating and self.conducts(e)
        ]

    def outlets(self, design: Design, node_id: str) -> list[Edge]:
        """Outgoing edges that carry fluid away from `node_id` in this mode.

        A branch that cannot reach a running CDU again is a dead leg: no circuit, so no flow.
        """
        return [e for e in design.outgoing(node_id) if e.dst in self.draining and self.conducts(e)]

    def demand_factor(self, cls: str | None) -> float:
        """Load factor for a load class in this mode; 1.0 when the mode does not name it."""
        return self.demand.get(str(cls), 1.0)


def _is_flow_source(kind: str, state: str) -> bool:
    return kind in SOURCE_KINDS and state == "on"


def resolve(design: Design, mode: Mode) -> ModeState:
    node_state = {nid: (n.state or "on") for nid, n in design.nodes.items()}
    device_state: dict[str, str] = {did: d.state for did, d in design.devices().items()}

    for target, value in mode.overrides.items():
        if target in node_state:
            node_state[target] = value
        else:
            device_state[target] = value

    live = [nid for nid, n in design.nodes.items() if _is_flow_source(n.kind, node_state[nid])]
    partial = ModeState(mode.name, node_state, device_state, mode.demand, mode.conditions)

    downstream: dict[str, list[str]] = {nid: [] for nid in design.nodes}
    upstream: dict[str, list[str]] = {nid: [] for nid in design.nodes}
    for edge in design.edges:
        if not partial.conducts(edge):
            continue
        downstream[edge.src].append(edge.dst)
        upstream[edge.dst].append(edge.src)
        if edge.bidirectional:
            downstream[edge.dst].append(edge.src)
            upstream[edge.src].append(edge.dst)

    def _reach(adjacency: dict[str, list[str]]) -> frozenset[str]:
        seen: set[str] = set()
        queue: deque[str] = deque(live)
        while queue:
            nid = queue.popleft()
            if nid in seen or node_state[nid] in _DEAD_STATES:
                continue
            seen.add(nid)
            queue.extend(adjacency[nid])
        return frozenset(seen)

    return ModeState(
        mode.name,
        node_state,
        device_state,
        mode.demand,
        mode.conditions,
        _reach(downstream),
        _reach(upstream),
    )
