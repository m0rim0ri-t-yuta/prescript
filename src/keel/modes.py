"""Per-mode state resolution and energization.

A mode overrides node and device states. From the resolved states we compute which nodes are
energized: a breadth-first walk from every live source over conducting edges, skipping dead nodes.
This is topology only — no load flow.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from keel.ir import Design, Edge, Mode

# Node states that stop a node from conducting or being energized.
_DEAD_STATES = {"off"}


@dataclass(frozen=True)
class ModeState:
    mode: str
    node_state: dict[str, str]
    device_state: dict[str, str]
    ats_selection: dict[str, str]
    energized: frozenset[str] = field(default_factory=frozenset)

    def conducts(self, edge: Edge) -> bool:
        """Can power cross this edge in this mode?"""
        if edge.role == "ats_leg":
            return self.ats_selection.get(edge.dst) == edge.src
        # A UPS in bypass has its inverter off: only the bypass input reaches the output.
        if edge.role == "rectifier_input" and self.node_state.get(edge.dst) == "bypass":
            return False
        return edge.via is None or self.device_state.get(edge.via.id, "closed") == "closed"

    def feeds(self, design: Design, node_id: str) -> list[Edge]:
        """Incoming edges that actually deliver power to `node_id` in this mode."""
        return [e for e in design.incoming(node_id) if e.src in self.energized and self.conducts(e)]


def _default_node_state(kind: str, declared: str | None) -> str:
    if declared is not None:
        return declared
    return "off" if kind == "generator" else "on"


def _is_live_source(kind: str, state: str) -> bool:
    if kind == "source":
        return state != "off"
    if kind == "generator":
        return state == "on"
    if kind == "ups":
        return state == "battery"
    return False


def resolve(design: Design, mode: Mode) -> ModeState:
    node_state = {nid: _default_node_state(n.kind, n.state) for nid, n in design.nodes.items()}
    device_state: dict[str, str] = {did: d.state for did, d in design.devices().items()}
    ats_selection = {
        nid: str(n.get("preferred")) for nid, n in design.nodes.items() if n.kind == "ats"
    }

    for target, value in mode.overrides.items():
        if isinstance(value, dict):
            ats_selection[target] = value["select"]
        elif target in node_state:
            node_state[target] = value
        else:
            device_state[target] = value

    live = [nid for nid, n in design.nodes.items() if _is_live_source(n.kind, node_state[nid])]
    partial = ModeState(mode.name, node_state, device_state, ats_selection)

    adjacency: dict[str, list[str]] = {nid: [] for nid in design.nodes}
    for edge in design.edges:
        if not partial.conducts(edge):
            continue
        adjacency[edge.src].append(edge.dst)
        if edge.bidirectional:
            adjacency[edge.dst].append(edge.src)

    energized: set[str] = set()
    queue: deque[str] = deque(live)
    while queue:
        nid = queue.popleft()
        if nid in energized or node_state[nid] in _DEAD_STATES:
            continue
        energized.add(nid)
        queue.extend(adjacency[nid])

    return ModeState(mode.name, node_state, device_state, ats_selection, frozenset(energized))
