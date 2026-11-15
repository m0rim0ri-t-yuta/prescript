"""Render an elaborated design as a cooling-loop diagram (SVG).

`draw` is a second consumer of the IR, beside `checks`: it shows what the netlist says — the
topology, the states of one operating mode, and the ratings as written. It is not a verification
result and not a hydraulic study, and it never fills in a number the spec has not decided: an
undecided rating is drawn as `?`, the same promise `UNRUN` keeps on the verification side.

Layout: a column is the distance from a CDU along the direction the coolant travels, so the figure
reads supply side to return side, left to right. The edges that close the loop back into a CDU are
cut before layering and drawn in return lanes under the diagram.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from xml.sax.saxutils import escape

from prescript.ir import SOURCE_KINDS, Design, Edge, Node
from prescript.modes import ModeState

# Geometry in user units (= px at 1:1).
_BOX_W = 168
_BOX_H = 50
_COL_GAP = 104
_ROW_GAP = 16
_MARGIN = 28
_HEAD_H = 84
_LANE_GAP = 20
_LEGEND_H = 56
# The legend is a fixed width: a one-CDU netlist must not be narrower than its own key.
_MIN_W = 640

_FONT = "ui-sans-serif, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"

# One fill per node kind; strokes stay in three inks only: live, muted and alert.
_FILL: dict[str, str] = {
    "cdu": "#dbeafe",
    "pump": "#e0e7ff",
    "header": "#e2e8f0",
    "manifold": "#ecfccb",
    "rack": "#fef3c7",
    "rdhx": "#fae8ff",
}
_INK = "#334155"
_MUTED_INK = "#94a3b8"
_MUTED_FILL = "#f8fafc"
_ALERT = "#b91c1c"
_PAPER = "#ffffff"

# Rated attributes shown in a box, in this order, with the unit the key name carries.
_BADGES: tuple[tuple[str, str], ...] = (
    ("rating_kw", "kW"),
    ("rating_lpm", "L/min"),
    ("rating_kpa", "kPa"),
    ("heat_kw", "kW"),
    ("delta_t_k", "K"),
)

# Node states that mean the element is not running (same set `modes` stops propagation on).
_STOPPED = frozenset({"off", "standby"})

_NOTE_NO_FLOW = "no flow"
_NOTE_DEAD_LEG = "dead leg"


@dataclass(frozen=True)
class _Box:
    """One node, placed."""

    node: Node
    x: float
    y: float
    muted: bool
    note: str

    @property
    def cx(self) -> float:
        return self.x + _BOX_W / 2

    @property
    def cy(self) -> float:
        return self.y + _BOX_H / 2


def _is_return(design: Design, edge: Edge) -> bool:
    """Does this edge close the loop back into a flow source?"""
    return design.nodes[edge.dst].kind in SOURCE_KINDS


def _layers(design: Design) -> dict[str, int]:
    """Column per node: the longest forward path from a CDU, with return edges cut."""
    forward = [e for e in design.edges if not _is_return(design, e)]
    succ: dict[str, list[str]] = defaultdict(list)
    pred: dict[str, list[str]] = defaultdict(list)
    indeg: dict[str, int] = dict.fromkeys(design.nodes, 0)
    for edge in forward:
        succ[edge.src].append(edge.dst)
        pred[edge.dst].append(edge.src)
        indeg[edge.dst] += 1

    layer: dict[str, int] = dict.fromkeys(design.nodes, 0)
    queue: deque[str] = deque(nid for nid, deg in indeg.items() if deg == 0)
    placed: set[str] = set()
    while queue:
        nid = queue.popleft()
        placed.add(nid)
        for dst in succ[nid]:
            layer[dst] = max(layer[dst], layer[nid] + 1)
            indeg[dst] -= 1
            if indeg[dst] == 0:
                queue.append(dst)

    # A cycle the return cut did not break (e.g. a bidirectional tie): place what is left after
    # its already-placed predecessors, in id order, so the layout stays deterministic.
    for nid in sorted(set(design.nodes) - placed):
        resolved = [layer[p] for p in pred[nid] if p in placed]
        layer[nid] = max(resolved) + 1 if resolved else 0
        placed.add(nid)
    return layer


def _note(node_id: str, state: ModeState | None) -> str:
    """What this mode says about the element: its stopped state, or why no fluid moves."""
    if state is None:
        return ""
    if (own := state.node_state.get(node_id, "on")) in _STOPPED:
        return own
    if node_id not in state.circulating:
        return _NOTE_NO_FLOW
    if node_id not in state.draining:
        return _NOTE_DEAD_LEG
    return ""


def _num(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return str(value)
    return f"{value:g}"


def _badges(node: Node) -> str:
    """Ratings as written. A rating the netlist leaves `null` is `?`, never a filled-in number."""
    parts = [
        f"{'?' if node.attrs[key] is None else _num(node.attrs[key])} {unit}"
        for key, unit in _BADGES
        if key in node.attrs
    ]
    return " · ".join(parts)


def _tooltip(node: Node, note: str) -> str:
    rows = [f"{node.id} — {node.kind}"]
    for key in sorted(node.attrs):
        value = node.attrs[key]
        rows.append(f"{key}: {'null' if value is None else value}")
    if node.provenance:
        rows.append(f"provenance: {node.provenance}")
    if node.origin:
        rows.append(f"origin: {node.origin}")
    if note:
        rows.append(f"state: {note}")
    return "\n".join(rows)


def _text(
    x: float,
    y: float,
    body: str,
    *,
    size: float = 11,
    fill: str = _INK,
    weight: str = "normal",
    anchor: str = "start",
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" '
        f'font-weight="{weight}" text-anchor="{anchor}">{escape(body)}</text>'
    )


def _boxes(design: Design, state: ModeState | None) -> dict[str, _Box]:
    layer = _layers(design)
    columns: dict[int, list[str]] = defaultdict(list)
    for nid in design.nodes:  # insertion order: elaboration order, so blocks stay together
        columns[layer[nid]].append(nid)
    tallest = max((len(ids) for ids in columns.values()), default=0)
    span = _BOX_H + _ROW_GAP

    boxes: dict[str, _Box] = {}
    for col, ids in columns.items():
        top = _HEAD_H + (tallest - len(ids)) * span / 2
        for row, nid in enumerate(ids):
            note = _note(nid, state)
            boxes[nid] = _Box(
                node=design.nodes[nid],
                x=_MARGIN + col * (_BOX_W + _COL_GAP),
                y=top + row * span,
                muted=note in _STOPPED or note == _NOTE_NO_FLOW,
                note=note,
            )
    return boxes


def _box_svg(box: _Box) -> str:
    ink = _MUTED_INK if box.muted else _INK
    fill = _MUTED_FILL if box.muted else _FILL.get(box.node.kind, _PAPER)
    dash = ' stroke-dasharray="4 3"' if box.muted else ""
    parts = [
        f"<g><title>{escape(_tooltip(box.node, box.note))}</title>",
        f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{_BOX_W}" height="{_BOX_H}" rx="6" '
        f'fill="{fill}" stroke="{ink}" stroke-width="1.2"{dash}/>',
        _text(box.x + 10, box.y + 18, box.node.id, size=11.5, fill=ink, weight="600"),
        _text(box.x + 10, box.y + 31, box.node.kind, size=9, fill=_MUTED_INK),
        _text(box.x + 10, box.y + 43, _badges(box.node), size=9, fill=ink),
    ]
    if box.note:
        parts.append(
            _text(box.x + _BOX_W - 10, box.y + 31, box.note, size=9, fill=_ALERT, anchor="end")
        )
    parts.append("</g>")
    return "".join(parts)


def _edge_title(edge: Edge, conducts: bool) -> str:
    rows = [f"{edge.src} → {edge.dst}"]
    if edge.via is not None:
        rows.append(f"{edge.via.kind} {edge.via.id}: {'open' if conducts else 'closed'}")
    if edge.share is not None:
        rows.append(f"share: {edge.share:g}")
    if edge.role is not None:
        rows.append(f"role: {edge.role}")
    return "\n".join(rows)


def _stroke(conducts: bool, muted: bool) -> tuple[str, str, str]:
    """Ink, dash attribute and arrow marker for an edge."""
    if not conducts:
        return _ALERT, ' stroke-dasharray="5 4"', "arrow-alert"
    if muted:
        return _MUTED_INK, ' stroke-dasharray="5 4"', "arrow-muted"
    return _INK, "", "arrow"


def _valve_svg(edge: Edge, x: float, y: float, conducts: bool, ink: str) -> str:
    if edge.via is None:
        return ""
    fill = _ALERT if not conducts else _PAPER
    marker = (
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{fill}" stroke="{ink}" '
        'stroke-width="1.2"/>'
    )
    if conducts:
        return marker
    # Left of the marker: the gap between the columns is empty, the destination box is not.
    label = _text(x - 9, y - 6, f"{edge.via.id} closed", size=8.5, fill=_ALERT, anchor="end")
    return marker + label


def _valve_at(
    design: Design, edge: Edge, near_src: tuple[float, float], near_dst: tuple[float, float]
) -> tuple[float, float]:
    """Put the valve marker on the leg that belongs to this edge alone.

    A supply header fans out to one branch per rack and every branch carries its own valve; marked
    at the header they would all land on one point. The crowded end loses.
    """
    if len(design.outgoing(edge.src)) >= len(design.incoming(edge.dst)):
        return near_dst
    return near_src


def _forward_svg(
    design: Design, edge: Edge, boxes: dict[str, _Box], state: ModeState | None
) -> str:
    src, dst = boxes[edge.src], boxes[edge.dst]
    conducts = state is None or state.conducts(edge)
    ink, dash, marker = _stroke(conducts, src.muted or dst.muted)
    x1, x2 = src.x + _BOX_W, dst.x
    mid = x1 + (x2 - x1) / 2 if x2 > x1 else x1 + _COL_GAP / 2
    points = (
        f"{x1:.1f},{src.cy:.1f} {mid:.1f},{src.cy:.1f} {mid:.1f},{dst.cy:.1f} {x2:.1f},{dst.cy:.1f}"
    )
    vx, vy = _valve_at(
        design,
        edge,
        (x1 + (mid - x1) / 2, src.cy),
        (mid + (x2 - mid) / 2, dst.cy),
    )
    return (
        f"<g><title>{escape(_edge_title(edge, conducts))}</title>"
        f'<polyline points="{points}" fill="none" stroke="{ink}" stroke-width="1.2"{dash} '
        f'marker-end="url(#{marker})"/>'
        f"{_valve_svg(edge, vx, vy, conducts, ink)}"
        "</g>"
    )


def _return_svg(edge: Edge, boxes: dict[str, _Box], state: ModeState | None, lane_y: float) -> str:
    src, dst = boxes[edge.src], boxes[edge.dst]
    conducts = state is None or state.conducts(edge)
    ink, dash, marker = _stroke(conducts, src.muted or dst.muted)
    points = (
        f"{src.cx:.1f},{src.y + _BOX_H:.1f} {src.cx:.1f},{lane_y:.1f} "
        f"{dst.cx:.1f},{lane_y:.1f} {dst.cx:.1f},{dst.y + _BOX_H:.1f}"
    )
    label_x = (src.cx + dst.cx) / 2
    return (
        f"<g><title>{escape(_edge_title(edge, conducts))}</title>"
        f'<polyline points="{points}" fill="none" stroke="{ink}" stroke-width="1.2"{dash} '
        f'marker-end="url(#{marker})"/>'
        f"{_text(label_x, lane_y - 5, 'return', size=9, fill=ink, anchor='middle')}"
        f"{_valve_svg(edge, label_x, lane_y, conducts, ink)}"
        "</g>"
    )


def _defs() -> str:
    markers = []
    for name, ink in (("arrow", _INK), ("arrow-muted", _MUTED_INK), ("arrow-alert", _ALERT)):
        markers.append(
            f'<marker id="{name}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" '
            f'markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M 0 1 L 7 4 L 0 7 z" fill="{ink}"/></marker>'
        )
    return f"<defs>{''.join(markers)}</defs>"


def _header_svg(design: Design, state: ModeState | None) -> str:
    mode = state.mode if state is not None else "no mode — states as written"
    return "".join(
        [
            _text(_MARGIN, 34, design.project, size=15, weight="700"),
            _text(
                _MARGIN,
                50,
                f"prescript draw · mode: {mode} · grammar v{design.prescript}",
                size=10,
                fill=_MUTED_INK,
            ),
            _text(
                _MARGIN,
                64,
                "Topology, states and ratings as the netlist writes them. `?` = undecided (null). "
                "Not a verification result and not a hydraulic study — run `prescript verify`.",
                size=9,
                fill=_MUTED_INK,
            ),
        ]
    )


def _legend_svg(y: float) -> str:
    parts = [_text(_MARGIN, y, "legend", size=9, fill=_MUTED_INK)]
    x = _MARGIN
    for kind, fill in _FILL.items():
        parts.append(
            f'<rect x="{x:.1f}" y="{y + 8:.1f}" width="11" height="11" rx="2" fill="{fill}" '
            f'stroke="{_INK}" stroke-width="1.2"/>'
        )
        parts.append(_text(x + 16, y + 17, kind, size=9))
        x += 104
    sample_y = y + 34
    parts += [
        f'<line x1="{_MARGIN}" y1="{sample_y:.1f}" x2="{_MARGIN + 22}" y2="{sample_y:.1f}" '
        f'stroke="{_MUTED_INK}" stroke-width="1.2" stroke-dasharray="5 4"/>',
        _text(_MARGIN + 28, sample_y + 3, "stopped / no flow", size=9, fill=_MUTED_INK),
        f'<line x1="{_MARGIN + 160}" y1="{sample_y:.1f}" x2="{_MARGIN + 182}" '
        f'y2="{sample_y:.1f}" stroke="{_ALERT}" stroke-width="1.2" stroke-dasharray="5 4"/>',
        _text(_MARGIN + 188, sample_y + 3, "valve closed / dead leg", size=9, fill=_ALERT),
        _text(_MARGIN + 356, sample_y + 3, "? = rating the netlist has not decided", size=9),
    ]
    return "".join(parts)


def to_svg(design: Design, state: ModeState | None = None) -> str:
    """The cooling loop as an SVG document. Pure: same design and mode, same bytes."""
    boxes = _boxes(design, state)
    returns = [e for e in design.edges if _is_return(design, e)]
    bottom = max((b.y + _BOX_H for b in boxes.values()), default=_HEAD_H)
    lanes = _LANE_GAP * len(returns)
    rightmost = max((b.x for b in boxes.values()), default=float(_MARGIN))
    width = max(rightmost + _BOX_W + _MARGIN, _MIN_W)
    legend_y = bottom + lanes + 28
    height = legend_y + _LEGEND_H

    body = [
        f'<rect x="0" y="0" width="{width:.1f}" height="{height:.1f}" fill="{_PAPER}"/>',
        _header_svg(design, state),
    ]
    body += [
        _forward_svg(design, edge, boxes, state)
        for edge in design.edges
        if not _is_return(design, edge)
    ]
    body += [
        _return_svg(edge, boxes, state, bottom + _LANE_GAP * (index + 1))
        for index, edge in enumerate(returns)
    ]
    body += [_box_svg(boxes[nid]) for nid in design.nodes]
    body.append(_legend_svg(legend_y))

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" font-family="{_FONT}">'
        f"{_defs()}{''.join(body)}</svg>\n"
    )
