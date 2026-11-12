from __future__ import annotations

from typing import Any

import pytest

from prescript.ir import Design
from prescript.loader import NetlistError, parse_design


def test_blocks_expand_into_eight_racks(design: Design) -> None:
    racks = [n for n in design.nodes.values() if n.id.startswith("RACK-")]
    assert len(racks) == 8
    assert all(n.get("rated_kw") == 150 for n in racks)
    assert racks[0].origin is not None and racks[0].origin.startswith("rack_gb200_nvl72")


def test_whole_placeholder_keeps_type(design: Design) -> None:
    assert design.nodes["PDU-A-01"].get("rating_a") == 300
    assert design.nodes["UPS-A"].get("rating_kva") == 1500


def test_on_off_are_states_not_booleans(design: Design) -> None:
    assert design.nodes["UPS-A"].state == "on"
    assert design.nodes["GEN-01"].state == "off"
    assert design.modes["maint-A"].overrides["TR-A"] == "off"


def test_ats_sources_become_synthetic_legs(design: Design) -> None:
    legs = [e for e in design.edges if e.dst == "ATS-01" and e.synthetic]
    assert {e.src for e in legs} == {"LVMSB-A", "GEN-01"}


def test_mode_all_expands_to_every_mode(design: Design) -> None:
    a06 = next(a for a in design.assertions if a.id == "A-06")
    assert set(a06.modes) == set(design.modes)


def test_dangling_edge_is_an_error(doc: dict[str, Any]) -> None:
    doc["edges"].append({"from": "DP-A", "to": "NOWHERE"})
    with pytest.raises(NetlistError, match="unknown node 'NOWHERE'"):
        parse_design(doc)


def test_provenance_is_mandatory(doc: dict[str, Any]) -> None:
    doc["nodes"].append({"id": "X-01", "kind": "load", "class": "critical", "rated_kw": 1})
    with pytest.raises(NetlistError, match="provenance is mandatory"):
        parse_design(doc)


def test_duplicate_ids_are_rejected(doc: dict[str, Any]) -> None:
    doc["nodes"].append({"id": "DP-A", "kind": "panel", "provenance": "assumed"})
    with pytest.raises(NetlistError, match="duplicate node id"):
        parse_design(doc)


def test_override_must_target_a_known_id(doc: dict[str, Any]) -> None:
    doc["modes"]["normal"]["overrides"] = {"GHOST": "off"}
    with pytest.raises(NetlistError, match="unknown id 'GHOST'"):
        parse_design(doc)


def test_unsupported_grammar_version(doc: dict[str, Any]) -> None:
    doc["prescript"] = 9.9
    with pytest.raises(NetlistError, match="unsupported grammar"):
        parse_design(doc)
