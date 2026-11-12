"""Power flow on the reference design, checked against hand calculations.

Reference: 8 racks x 150 kW + AUX-01 80 kW = 1280 kW critical, split A/B by share 0.5.
Essential: duty CDU 30 + PMP 15 + CRAH 20 + BMS 10 = 75 kW; standby 30 + 15 + 20 = 65 kW.
"""

from __future__ import annotations

from typing import Any

import pytest

from prescript import flow
from prescript.ir import Design
from prescript.loader import parse_design
from prescript.modes import resolve


def _flow(design: Design, mode: str) -> flow.Flow:
    return flow.compute(design, resolve(design, design.modes[mode]), design.modes[mode].demand)


def test_normal_splits_critical_evenly(design: Design) -> None:
    f = _flow(design, "normal")
    assert f.node_kw["UPS-A"] == pytest.approx(640)
    assert f.node_kw["UPS-B"] == pytest.approx(640)
    assert f.node_kw["PDU-A-01"] == pytest.approx(75)
    # Essential duty loads only (standby demand is 0 in normal), via ATS-01 from LVMSB-A.
    assert f.node_kw["EM-BUS"] == pytest.approx(75)
    assert f.node_kw["LVMSB-A"] == pytest.approx(640 + 75)
    assert f.missing == ()


def test_maint_a_moves_everything_to_side_b(design: Design) -> None:
    f = _flow(design, "maint-A")
    assert f.node_kw.get("UPS-A", 0) == 0
    assert f.node_kw["UPS-B"] == pytest.approx(1280)
    assert f.node_kw["PDU-B-03"] == pytest.approx(150)
    # Shares renormalise over live feeds: AUX-01 takes all 80 kW from DP-B.
    assert f.node_kw["DP-B"] == pytest.approx(1280)
    # Essential duty + standby (140 kW) now reach EM-BUS through ATS-02 from LVMSB-B.
    assert f.node_kw["LVMSB-B"] == pytest.approx(1280 + 140)
    assert f.node_kw["TR-B"] == pytest.approx(1420)


def test_generator_mode_ups_on_battery_absorbs_critical(design: Design) -> None:
    f = _flow(design, "generator")
    assert f.node_kw["GEN-01"] == pytest.approx(140)
    assert f.node_kw["UPS-A"] == pytest.approx(640)
    assert f.node_kw.get("LVMSB-A", 0) == 0


def test_closed_tie_carries_nothing_when_both_sides_are_fed(design: Design) -> None:
    f = _flow(design, "tie-closed")
    tie = next(i for i, e in enumerate(design.edges) if e.via is not None and e.via.id == "TIE-AB")
    assert f.edge_kw.get(tie, 0) == 0


def test_closed_tie_feeds_the_dead_side(doc: dict[str, Any]) -> None:
    doc["modes"]["tie-backfeed"] = {
        "overrides": {"UTIL-A": "off", "TIE-AB": "closed"},
        "demand": {"critical": 1.0, "essential_duty": 1.0, "essential_standby": 0.0},
    }
    d = parse_design(doc)
    f = _flow(d, "tie-backfeed")
    assert f.node_kw.get("TR-A", 0) == 0
    assert f.node_kw["TR-B"] == pytest.approx(1280 + 75)


def test_missing_demand_factor_is_reported(doc: dict[str, Any]) -> None:
    doc["modes"]["normal"]["demand"] = {"critical": 1.0}
    f = _flow(parse_design(doc), "normal")
    assert "mode[normal].demand.essential_duty" in f.missing


def test_null_rated_kw_is_reported(doc: dict[str, Any]) -> None:
    doc["nodes"].append(
        {
            "id": "X-01",
            "kind": "load",
            "class": "critical",
            "rated_kw": None,
            "provenance": "assumed",
        }
    )
    doc["edges"].append({"from": "DP-A", "to": "X-01"})
    f = _flow(parse_design(doc), "normal")
    assert "X-01.rated_kw" in f.missing
