"""Load a Keel netlist (YAML, grammar v0.1) and elaborate it into the IR.

Grammar SSOT: docs/KEEL-LANGUAGE.md. This module implements it; change both together.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from keel.ir import (
    DEVICE_KINDS,
    META_MODE,
    NODE_KINDS,
    STATIC_MODE,
    Assertion,
    Design,
    Device,
    Edge,
    Mode,
    Node,
)

SUPPORTED_GRAMMAR = {"0.1"}
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_NODE_KEYS = {"id", "kind", "state", "provenance"}
_DEVICE_KEYS = {"id", "kind", "state", "provenance"}
# Rated kinds must carry provenance (AGENTS.md -> "Provenance is mandatory").
_RATED_KINDS = {"source", "transformer", "bus", "panel", "ups", "generator", "load"}


class NetlistError(ValueError):
    """The netlist is malformed. Messages name the offending element."""


class _Yaml12BoolLoader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 booleans: only true/false. `on`/`off`/`yes`/`no` stay strings,
    because `on`/`off` are equipment states in this grammar (docs/KEEL-LANGUAGE.md)."""


_Yaml12BoolLoader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:bool"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Yaml12BoolLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


# ------------------------------------------------------------------ templating ---


def _substitute(value: Any, params: dict[str, Any]) -> Any:
    """Replace {name} placeholders; a string that is exactly one placeholder keeps its type."""
    if isinstance(value, str):
        whole = _PLACEHOLDER.fullmatch(value)
        if whole:
            key = whole.group(1)
            if key not in params:
                raise NetlistError(f"unknown template parameter {{{key}}}")
            return params[key]

        def repl(m: re.Match[str]) -> str:
            if m.group(1) not in params:
                raise NetlistError(f"unknown template parameter {{{m.group(1)}}}")
            return str(params[m.group(1)])

        return _PLACEHOLDER.sub(repl, value)
    if isinstance(value, dict):
        return {k: _substitute(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, params) for v in value]
    return value


def _elaborate(
    raw_nodes: list[dict[str, Any]],
    blocks: dict[str, Any],
) -> tuple[list[tuple[dict[str, Any], str | None]], list[dict[str, Any]]]:
    """Expand `{use: <block>, ...}` entries into plain node and edge dicts."""
    nodes: list[tuple[dict[str, Any], str | None]] = []
    edges: list[dict[str, Any]] = []
    for entry in raw_nodes:
        if "use" not in entry:
            nodes.append((entry, None))
            continue
        name = entry["use"]
        if name not in blocks:
            raise NetlistError(f"unknown block '{name}'")
        block = blocks[name]
        args = {k: v for k, v in entry.items() if k != "use"}
        params = {**block.get("params", {}), **args}
        origin = f"{name}[{', '.join(f'{k}={v}' for k, v in args.items())}]"
        block_prov = block.get("provenance")
        for tmpl in block.get("expands_to", []):
            node = _substitute(tmpl, params)
            node.setdefault("provenance", block_prov)
            nodes.append((node, origin))
        for tmpl in block.get("edges", []):
            edges.append(_substitute(tmpl, params))
    return nodes, edges


# ----------------------------------------------------------------- conversion ---


def _to_node(raw: dict[str, Any], origin: str | None) -> Node:
    if "id" not in raw or "kind" not in raw:
        raise NetlistError(f"node needs id and kind: {raw}")
    if raw["kind"] not in NODE_KINDS:
        raise NetlistError(f"node {raw['id']}: unknown kind '{raw['kind']}'")
    if raw["kind"] in _RATED_KINDS and not raw.get("provenance"):
        raise NetlistError(f"node {raw['id']}: provenance is mandatory for kind '{raw['kind']}'")
    attrs = {k: v for k, v in raw.items() if k not in _NODE_KEYS}
    try:
        return Node(
            id=str(raw["id"]),
            kind=raw["kind"],
            attrs=attrs,
            state=raw.get("state"),
            provenance=raw.get("provenance"),
            origin=origin,
        )
    except ValidationError as exc:
        raise NetlistError(f"node {raw['id']}: {exc}") from exc


def _to_device(raw: dict[str, Any], edge_label: str) -> Device:
    if "id" not in raw or "kind" not in raw:
        raise NetlistError(f"edge {edge_label}: via needs id and kind")
    if raw["kind"] not in DEVICE_KINDS:
        raise NetlistError(f"device {raw['id']}: unknown kind '{raw['kind']}'")
    attrs = {k: v for k, v in raw.items() if k not in _DEVICE_KEYS}
    try:
        return Device(
            id=str(raw["id"]),
            kind=raw["kind"],
            attrs=attrs,
            state=raw.get("state", "closed"),
            provenance=raw.get("provenance"),
        )
    except ValidationError as exc:
        raise NetlistError(f"device {raw['id']}: {exc}") from exc


def _to_edge(raw: dict[str, Any]) -> Edge:
    try:
        src, dst = str(raw["from"]), str(raw["to"])
    except KeyError as exc:
        raise NetlistError(f"edge needs from and to: {raw}") from exc
    label = f"{src}->{dst}"
    via = _to_device(raw["via"], label) if raw.get("via") else None
    unknown = set(raw) - {"from", "to", "via", "share", "bidirectional", "role"}
    if unknown:
        raise NetlistError(f"edge {label}: unknown keys {sorted(unknown)}")
    return Edge(
        src=src,
        dst=dst,
        via=via,
        share=raw.get("share"),
        bidirectional=bool(raw.get("bidirectional", False)),
        role=raw.get("role"),
    )


def _ats_legs(nodes: dict[str, Node]) -> list[Edge]:
    """An ATS declares `sources:`; elaboration turns them into synthetic supply edges."""
    legs: list[Edge] = []
    for node in nodes.values():
        if node.kind != "ats":
            continue
        sources = node.get("sources") or []
        if len(sources) < 2:
            raise NetlistError(f"ats {node.id}: needs at least two sources")
        preferred = node.get("preferred")
        if preferred not in sources:
            raise NetlistError(f"ats {node.id}: preferred '{preferred}' is not one of its sources")
        for src in sources:
            legs.append(Edge(src=str(src), dst=node.id, role="ats_leg", synthetic=True))
    return legs


def _to_assertion(raw: dict[str, Any], mode_names: set[str]) -> Assertion:
    modes_raw = raw.get("modes", "all")
    if modes_raw == "all":
        modes: tuple[str, ...] = tuple(sorted(mode_names))
    elif isinstance(modes_raw, list):
        modes = tuple(str(m) for m in modes_raw)
    else:
        raise NetlistError(f"assertion {raw.get('id')}: modes must be 'all' or a list")
    for m in modes:
        if m not in mode_names and m not in (STATIC_MODE, META_MODE):
            raise NetlistError(f"assertion {raw.get('id')}: unknown mode '{m}'")
    severity = raw.get("severity", "error")
    return Assertion(
        id=str(raw["id"]),
        check=str(raw["check"]),
        args=raw.get("args") or {},
        modes=modes,
        severity="warn" if severity == "warn" else "error",
    )


# ----------------------------------------------------------------- validation ---


def _validate(design: Design) -> None:
    ids = set(design.nodes)
    device_ids: set[str] = set()
    for edge in design.edges:
        for end in (edge.src, edge.dst):
            if end not in ids:
                raise NetlistError(f"edge {edge.src}->{edge.dst}: unknown node '{end}'")
        if edge.via is not None:
            if edge.via.id in ids or edge.via.id in device_ids:
                raise NetlistError(f"duplicate id '{edge.via.id}'")
            device_ids.add(edge.via.id)
    targets = ids | device_ids
    for mode in design.modes.values():
        for target, value in mode.overrides.items():
            if target not in targets:
                raise NetlistError(f"mode {mode.name}: override targets unknown id '{target}'")
            if isinstance(value, dict):
                selected = value.get("select")
                node = design.nodes.get(target)
                if node is None or node.kind != "ats":
                    raise NetlistError(f"mode {mode.name}: 'select' only applies to an ats")
                if selected not in (node.get("sources") or []):
                    raise NetlistError(f"mode {mode.name}: {target} cannot select '{selected}'")


# --------------------------------------------------------------------- public ---


def load_design(path: str | Path) -> Design:
    with open(path, encoding="utf-8") as fh:
        doc = yaml.load(fh, Loader=_Yaml12BoolLoader)  # SafeLoader subclass
    return parse_design(doc)


def parse_design(doc: dict[str, Any]) -> Design:
    if not isinstance(doc, dict):
        raise NetlistError("netlist must be a mapping")
    grammar = str(doc.get("keel"))
    if grammar not in SUPPORTED_GRAMMAR:
        raise NetlistError(f"unsupported grammar version keel: {grammar}")

    raw_nodes, block_edges = _elaborate(doc.get("nodes") or [], doc.get("blocks") or {})
    nodes: dict[str, Node] = {}
    for raw, origin in raw_nodes:
        node = _to_node(raw, origin)
        if node.id in nodes:
            raise NetlistError(f"duplicate node id '{node.id}'")
        nodes[node.id] = node

    edges = [_to_edge(e) for e in [*block_edges, *(doc.get("edges") or [])]]
    edges.extend(_ats_legs(nodes))

    modes = {
        str(name): Mode(
            name=str(name),
            overrides=body.get("overrides") or {},
            demand=body.get("demand") or {},
            note=body.get("note"),
        )
        for name, body in (doc.get("modes") or {}).items()
    }
    assertions = tuple(_to_assertion(a, set(modes)) for a in doc.get("assertions") or [])
    seen: set[str] = set()
    for a in assertions:
        if a.id in seen:
            raise NetlistError(f"duplicate assertion id '{a.id}'")
        seen.add(a.id)

    try:
        design = Design(
            keel=grammar,
            project=str(doc.get("project", "unnamed")),
            units=doc.get("units") or {},
            nodes=nodes,
            edges=tuple(edges),
            modes=modes,
            assertions=assertions,
        )
    except ValidationError as exc:
        raise NetlistError(str(exc)) from exc
    _validate(design)
    return design
