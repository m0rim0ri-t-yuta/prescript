from __future__ import annotations

from typing import Any

import pytest

from prescript.ir import Design
from prescript.loader import NetlistError, parse_design


def test_blocks_expand_into_eight_racks(design: Design) -> None:
    racks = [n for n in design.nodes.values() if n.kind == "rack"]
    assert len(racks) == 8
    assert all(n.get("heat_kw") == 150 for n in racks)
    assert racks[0].origin is not None and racks[0].origin.startswith("rack_gb200_nvl72")


def test_whole_placeholder_keeps_type(design: Design) -> None:
    assert design.nodes["MAN-A-01"].get("rating_lpm") == 300
    assert design.nodes["CDU-A"].get("rating_kw") == 1500


def test_on_off_are_states_not_booleans(design: Design) -> None:
    assert design.nodes["PMP-A-1"].state is None  # defaults to on
    assert design.nodes["PMP-A-2"].state == "standby"
    assert design.modes["maint-cdu-A"].overrides["CDU-A"] == "off"


def test_valves_default_to_open(design: Design) -> None:
    assert design.devices()["V-SA-01"].state == "open"


def test_a_valve_state_must_be_open_or_closed(doc: dict[str, Any]) -> None:
    doc["edges"].append(
        {"from": "HDR-S-A", "to": "RDHX-01", "via": {"id": "V-X", "kind": "valve", "state": "on"}}
    )
    with pytest.raises(NetlistError, match="state must be open or closed"):
        parse_design(doc)


def test_fluid_properties_reach_the_ir(design: Design) -> None:
    assert design.fluids["pg25"].volumetric_heat_kj_lk() == pytest.approx(3.9655)
    assert design.fluid_of(design.nodes["RACK-01"]) is design.fluids["pg25"]


def test_an_undeclared_fluid_is_an_error(doc: dict[str, Any]) -> None:
    doc["nodes"].append(
        {"id": "X-01", "kind": "manifold", "fluid": "water", "provenance": "assumed"}
    )
    with pytest.raises(NetlistError, match="unknown fluid 'water'"):
        parse_design(doc)


def test_fluid_provenance_is_mandatory(doc: dict[str, Any]) -> None:
    doc["fluids"]["water"] = {"cp_kj_kgk": 4.18, "density_kg_l": 1.0}
    with pytest.raises(NetlistError, match="provenance is mandatory"):
        parse_design(doc)


def test_mode_all_expands_to_every_mode(doc: dict[str, Any]) -> None:
    doc["assertions"].append({"id": "Z-01", "check": "loop_closed", "modes": "all"})
    d = parse_design(doc)
    z01 = next(a for a in d.assertions if a.id == "Z-01")
    assert set(z01.modes) == set(d.modes)


def test_loading_is_not_asserted_where_nothing_circulates(design: Design) -> None:
    """facility-loss stops both CDUs, so `loading` could never mean anything there (#15)."""
    c05 = next(a for a in design.assertions if a.id == "C-05")
    assert set(c05.modes) == set(design.modes) - {"facility-loss"}


def test_mode_conditions_are_carried(design: Design) -> None:
    assert design.modes["summer-peak"].conditions["facility_supply_c"] == 32


def test_dangling_edge_is_an_error(doc: dict[str, Any]) -> None:
    doc["edges"].append({"from": "HDR-S-A", "to": "NOWHERE"})
    with pytest.raises(NetlistError, match="unknown node 'NOWHERE'"):
        parse_design(doc)


def test_provenance_is_mandatory(doc: dict[str, Any]) -> None:
    doc["nodes"].append({"id": "X-01", "kind": "manifold", "rating_lpm": 100})
    with pytest.raises(NetlistError, match="provenance is mandatory"):
        parse_design(doc)


def test_duplicate_ids_are_rejected(doc: dict[str, Any]) -> None:
    doc["nodes"].append({"id": "CDU-A", "kind": "cdu", "provenance": "assumed"})
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
