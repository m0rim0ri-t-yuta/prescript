"""`draw` renders the netlist; it never invents a number and never leaves the canvas."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from prescript import modes
from prescript.draw import to_svg
from prescript.ir import Design
from prescript.loader import parse_design

SVG = "{http://www.w3.org/2000/svg}"


def _svg(design: Design, mode: str | None = None) -> str:
    state = modes.resolve(design, design.modes[mode]) if mode is not None else None
    return to_svg(design, state)


def _root(svg: str) -> ET.Element:
    return ET.fromstring(svg.encode("utf-8"))


def _texts(root: ET.Element) -> list[str]:
    return [el.text or "" for el in root.iter(f"{SVG}text")]


def _group(root: ET.Element, subject: str) -> ET.Element:
    """The <g> whose <title> names this node or edge."""
    for group in root.iter(f"{SVG}g"):
        title = group.find(f"{SVG}title")
        if title is not None and (title.text or "").startswith(subject):
            return group
    raise AssertionError(f"no group titled {subject!r}")


def test_draws_every_node_with_its_ratings(design: Design) -> None:
    root = _root(_svg(design))
    for node_id, node in design.nodes.items():
        title = _group(root, f"{node_id} — {node.kind}").find(f"{SVG}title")
        assert title is not None
    assert "1500 kW · 2300 L/min" in _texts(root)  # CDU-A, as the netlist writes it


def test_a_decided_rating_is_drawn_as_the_netlist_writes_it(design: Design) -> None:
    assert "2300 L/min · 250 kPa" in _texts(_root(_svg(design)))  # the pumps' rated head


def test_an_undecided_rating_is_drawn_as_a_question_mark(doc: dict[str, Any]) -> None:
    """Undecided stays undecided: the figure says `?`, it does not fill in a number."""
    doc["blocks"]["cdu_loop"]["params"]["head_kpa"] = None
    design = parse_design(doc)
    assert design.nodes["PMP-A-1"].get("rating_kpa") is None
    texts = _texts(_root(to_svg(design)))
    assert "2300 L/min · ? kPa" in texts
    assert not any("0 kPa" in t for t in texts)


def test_a_mode_shows_what_stopped_and_what_stopped_flowing(design: Design) -> None:
    root = _root(_svg(design, "maint-cdu-A"))
    texts = _texts(root)
    assert "off" in texts  # CDU-A
    assert "standby" in texts  # PMP-A-2
    assert "no flow" in texts  # HDR-S-A and the A-side manifolds
    stopped = _group(root, "CDU-A —").find(f"{SVG}rect")
    assert stopped is not None and stopped.get("stroke-dasharray")
    live = _group(root, "CDU-B —").find(f"{SVG}rect")
    assert live is not None and not live.get("stroke-dasharray")


def test_without_a_mode_nothing_is_stopped(design: Design) -> None:
    texts = _texts(_root(_svg(design)))
    assert "off" not in texts
    assert "no flow" not in texts


def test_a_closed_valve_is_named(design: Design) -> None:
    assert "V-SA-01 closed" in _texts(_root(_svg(design, "valve-shut-01")))
    assert "V-SA-01 closed" not in _texts(_root(_svg(design, "normal")))


def test_everything_drawn_stays_inside_the_canvas(design: Design) -> None:
    """The canvas is sized from the layout, so the last column (the return headers) fits."""
    root = _root(_svg(design))
    width, height = float(root.get("width", "0")), float(root.get("height", "0"))
    for rect in root.iter(f"{SVG}rect"):
        right = float(rect.get("x", "0")) + float(rect.get("width", "0"))
        bottom = float(rect.get("y", "0")) + float(rect.get("height", "0"))
        assert right <= width and bottom <= height


def test_the_same_design_draws_the_same_bytes(design: Design) -> None:
    assert _svg(design) == _svg(design)
    assert _svg(design, "normal") == _svg(design, "normal")
    assert _svg(design, "normal") != _svg(design, "maint-cdu-A")
