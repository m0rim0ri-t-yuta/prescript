"""Load a Prescript netlist (YAML, grammar v0.2) and elaborate it into the IR.

Grammar SSOT: docs/PRESCRIPT-LANGUAGE.md. This module implements it; change both together.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from prescript.ir import (
    DEVICE_KINDS,
    META_MODE,
    NODE_KINDS,
    STATIC_MODE,
    Assertion,
    Design,
    Device,
    Edge,
    Fluid,
    Mode,
    Node,
    SpecTable,
)

SUPPORTED_GRAMMAR = {"0.2"}
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_NODE_KEYS = {"id", "kind", "state", "provenance"}
_DEVICE_KEYS = {"id", "kind", "state", "provenance"}
_VALVE_STATES = {"open", "closed"}
# Everything in a cooling loop carries ratings, so provenance is mandatory on every node kind
# (AGENTS.md -> "Provenance is mandatory").
_RATED_KINDS = NODE_KINDS


class NetlistError(ValueError):
    """The netlist is malformed. Messages name the offending element."""


class _Yaml12BoolLoader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 booleans: only true/false. `on`/`off`/`yes`/`no` stay strings,
    because `on`/`off` are equipment states in this grammar (docs/PRESCRIPT-LANGUAGE.md)."""


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
) -> tuple[list[tuple[dict[str, Any], str | None]], list[tuple[dict[str, Any], str | None]]]:
    """Expand `{use: <block>, ...}` entries into plain node and edge dicts, each with its block."""
    nodes: list[tuple[dict[str, Any], str | None]] = []
    edges: list[tuple[dict[str, Any], str | None]] = []
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
            edges.append((_substitute(tmpl, params), origin))
    return nodes, edges


# ----------------------------------------------------------------- conversion ---


def _to_fluid(name: str, raw: dict[str, Any]) -> Fluid:
    if not raw.get("provenance"):
        raise NetlistError(f"fluid {name}: provenance is mandatory")
    unknown = set(raw) - {"cp_kj_kgk", "density_kg_l", "viscosity_mpas", "provenance"}
    if unknown:
        raise NetlistError(f"fluid {name}: unknown keys {sorted(unknown)}")
    try:
        return Fluid(name=name, **raw)
    except ValidationError as exc:
        raise NetlistError(f"fluid {name}: {exc}") from exc


def _to_spec(name: str, raw: dict[str, Any]) -> SpecTable:
    """One transcribed sheet: `{provenance, rows: [{id, <field>: <value>, ...}]}`."""
    if not isinstance(raw, dict):
        raise NetlistError(f"spec table {name}: must be a mapping")
    unknown = set(raw) - {"provenance", "rows"}
    if unknown:
        raise NetlistError(f"spec table {name}: unknown keys {sorted(unknown)}")
    if not raw.get("provenance"):
        raise NetlistError(f"spec table {name}: provenance is mandatory")
    rows: dict[str, dict[str, Any]] = {}
    for row in raw.get("rows") or []:
        if not isinstance(row, dict) or "id" not in row:
            raise NetlistError(f"spec table {name}: every row needs an id: {row}")
        row_id = str(row["id"])
        if row_id in rows:
            raise NetlistError(f"spec table {name}: duplicate row id '{row_id}'")
        rows[row_id] = {k: v for k, v in row.items() if k != "id"}
    if not rows:
        raise NetlistError(f"spec table {name}: no rows")
    return SpecTable(name=name, rows=rows, provenance=str(raw["provenance"]))


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
    state = raw.get("state", "open")
    if state not in _VALVE_STATES:
        raise NetlistError(f"device {raw['id']}: state must be open or closed, not '{state}'")
    attrs = {k: v for k, v in raw.items() if k not in _DEVICE_KEYS}
    try:
        return Device(
            id=str(raw["id"]),
            kind=raw["kind"],
            attrs=attrs,
            state=state,
            provenance=raw.get("provenance"),
        )
    except ValidationError as exc:
        raise NetlistError(f"device {raw['id']}: {exc}") from exc


def _to_edge(raw: dict[str, Any], origin: str | None = None) -> Edge:
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
        origin=origin,
    )


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
    for node in design.nodes.values():
        fluid = node.get("fluid")
        if fluid is not None and str(fluid) not in design.fluids:
            raise NetlistError(f"node {node.id}: unknown fluid '{fluid}'")
    targets = ids | device_ids
    for mode in design.modes.values():
        for target in mode.overrides:
            if target not in targets:
                raise NetlistError(f"mode {mode.name}: override targets unknown id '{target}'")


# --------------------------------------------------------------------- public ---


def load_design(path: str | Path) -> Design:
    with open(path, encoding="utf-8") as fh:
        doc = yaml.load(fh, Loader=_Yaml12BoolLoader)  # SafeLoader subclass
    return parse_design(doc)


def parse_design(doc: dict[str, Any]) -> Design:
    if not isinstance(doc, dict):
        raise NetlistError("netlist must be a mapping")
    grammar = str(doc.get("prescript"))
    if grammar not in SUPPORTED_GRAMMAR:
        raise NetlistError(f"unsupported grammar version prescript: {grammar}")

    fluids = {str(n): _to_fluid(str(n), body) for n, body in (doc.get("fluids") or {}).items()}
    spec = {str(n): _to_spec(str(n), body) for n, body in (doc.get("spec") or {}).items()}
    raw_nodes, block_edges = _elaborate(doc.get("nodes") or [], doc.get("blocks") or {})
    nodes: dict[str, Node] = {}
    for raw, origin in raw_nodes:
        node = _to_node(raw, origin)
        if node.id in nodes:
            raise NetlistError(f"duplicate node id '{node.id}'")
        nodes[node.id] = node

    hand_written = [(e, None) for e in (doc.get("edges") or [])]
    edges = [_to_edge(raw, origin) for raw, origin in [*block_edges, *hand_written]]

    modes = {
        str(name): Mode(
            name=str(name),
            overrides=body.get("overrides") or {},
            demand=body.get("demand") or {},
            conditions=body.get("conditions") or {},
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
            prescript=grammar,
            project=str(doc.get("project", "unnamed")),
            units=doc.get("units") or {},
            fluids=fluids,
            spec=spec,
            nodes=nodes,
            edges=tuple(edges),
            modes=modes,
            assertions=assertions,
        )
    except ValidationError as exc:
        raise NetlistError(str(exc)) from exc
    _validate(design)
    return design
