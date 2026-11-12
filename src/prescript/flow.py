"""Per-mode power flow (simplified): push each load's demand up its live feeds.

Method — named in every result that uses it (verification-semantics.md §6):
- Demand of a load = `rated_kw` x the mode's demand factor for its class.
- A node's throughput is split across its live feeds by `share`, renormalised over the feeds that
  are live in this mode (equal split when no share is given).
- A bidirectional edge (bus tie) is used as a feed only when the node has no other live feed.
- Live sources (utility, running generator, UPS on battery) absorb what reaches them.
- Lossless: UPS and transformer efficiency, UPS recharge and reactive flow are ignored.

This is a screening estimate for topology-level loading, not a load-flow study.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from prescript.ir import Design, Edge, Node
from prescript.modes import ModeState

METHOD = "lossless radial flow"

# Demand-factor key for each load, read from the mode's `demand:` map.
CRITICAL = "critical"
ESSENTIAL_DUTY = "essential_duty"
ESSENTIAL_STANDBY = "essential_standby"


def demand_key(load: Node) -> str | None:
    cls = load.get("class")
    if cls == "critical":
        return CRITICAL
    if cls == "essential":
        return ESSENTIAL_STANDBY if load.get("standby_of") else ESSENTIAL_DUTY
    return None


@dataclass(frozen=True)
class Feed:
    """Power reaches `node` from `upstream` over `edge`."""

    node: str
    upstream: str
    edge: Edge
    weight: float


@dataclass(frozen=True)
class Flow:
    mode: str
    node_kw: dict[str, float]
    edge_kw: dict[int, float]  # index into design.edges
    missing: tuple[str, ...] = field(default=())


def _is_live_source(node: Node, state: ModeState) -> bool:
    s = state.node_state.get(node.id)
    return (
        (node.kind == "source" and s != "off")
        or (node.kind == "generator" and s == "on")
        or (node.kind == "ups" and s == "battery")
    )


def live_feeds(design: Design, state: ModeState, node_id: str) -> list[Feed]:
    node = design.nodes[node_id]
    if node_id not in state.energized or _is_live_source(node, state):
        return []
    direct: list[Edge] = []
    ties: list[tuple[Edge, str]] = []
    for e in design.edges:
        if not state.conducts(e):
            continue
        if e.dst == node_id and e.src in state.energized:
            (ties.append((e, e.src)) if e.bidirectional else direct.append(e))
        elif e.bidirectional and e.src == node_id and e.dst in state.energized:
            ties.append((e, e.dst))
    chosen = [(e, e.src) for e in direct] if direct else ties
    if not chosen:
        return []
    shares = [e.share for e, _ in chosen]
    if all(s is not None for s in shares):
        total = sum(s for s in shares if s is not None)
        weights = (
            [(s or 0.0) / total for s in shares] if total > 0 else [1 / len(chosen)] * len(chosen)
        )
    else:
        weights = [1 / len(chosen)] * len(chosen)
    return [Feed(node_id, up, e, w) for (e, up), w in zip(chosen, weights, strict=True)]


def compute(design: Design, state: ModeState, demand: dict[str, float]) -> Flow:
    missing: list[str] = []
    own: dict[str, float] = defaultdict(float)
    for load in design.nodes_of("load"):
        if load.id not in state.energized:
            continue
        key = demand_key(load)
        rated = load.get("rated_kw")
        if key is None:
            missing.append(f"{load.id}.class")
            continue
        if key not in demand:
            missing.append(f"mode[{state.mode}].demand.{key}")
            continue
        if rated is None:
            missing.append(f"{load.id}.rated_kw")
            continue
        own[load.id] = float(rated) * float(demand[key])

    feeds = {nid: live_feeds(design, state, nid) for nid in design.nodes}
    # Kahn order from the leaves of the feed graph upwards.
    pending: dict[str, int] = defaultdict(int)
    for fs in feeds.values():
        for f in fs:
            pending[f.upstream] += 1
    ready = [nid for nid in design.nodes if pending[nid] == 0]
    node_kw: dict[str, float] = defaultdict(float)
    edge_kw: dict[int, float] = defaultdict(float)
    index = {id(e): i for i, e in enumerate(design.edges)}
    seen = 0
    while ready:
        nid = ready.pop()
        seen += 1
        node_kw[nid] += own.get(nid, 0.0)
        for f in feeds[nid]:
            kw = node_kw[nid] * f.weight
            edge_kw[index[id(f.edge)]] += kw
            node_kw[f.upstream] += kw
            pending[f.upstream] -= 1
            if pending[f.upstream] == 0:
                ready.append(f.upstream)
    if seen != len(design.nodes):
        missing.append(f"mode[{state.mode}]: feed loop, flow undefined")
    return Flow(state.mode, dict(node_kw), dict(edge_kw), tuple(sorted(set(missing))))
