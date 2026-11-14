from __future__ import annotations

from typing import Any

from prescript.ir import Design
from prescript.loader import parse_design
from prescript.modes import resolve


def test_normal_circulates_both_sides(design: Design) -> None:
    s = resolve(design, design.modes["normal"])
    assert {"CDU-A", "CDU-B", "HDR-S-A", "HDR-R-B", "RACK-01", "RDHX-01"} <= s.circulating
    assert "PMP-A-2" not in s.circulating  # the standby pump is not running


def test_maint_takes_one_cdu_down(design: Design) -> None:
    s = resolve(design, design.modes["maint-cdu-A"])
    assert "HDR-S-A" not in s.circulating
    assert {"HDR-S-B", "RACK-01"} <= s.circulating


def test_a_stopped_cdu_leaves_its_return_header_a_dead_leg(design: Design) -> None:
    """Fluid can enter HDR-R-A but cannot get back to a running CDU, so it carries no flow."""
    s = resolve(design, design.modes["maint-cdu-A"])
    assert "HDR-R-A" in s.circulating
    assert "HDR-R-A" not in s.draining


def test_standby_pump_takes_over(design: Design) -> None:
    s = resolve(design, design.modes["pump-fail-A"])
    assert "PMP-A-1" not in s.circulating
    assert {"PMP-A-2", "HDR-S-A"} <= s.circulating


def test_a_closed_valve_does_not_conduct(design: Design) -> None:
    s = resolve(design, design.modes["normal"])
    branch = next(e for e in design.edges if e.via is not None and e.via.id == "V-SA-01")
    assert s.conducts(branch)
    shut = resolve(design, design.modes["valve-shut-01"])
    assert not shut.conducts(branch)
    assert "MAN-A-01" not in shut.circulating


def test_both_cdus_stopped_means_nothing_circulates(doc: dict[str, Any]) -> None:
    d = parse_design(doc)
    s = resolve(d, d.modes["facility-loss"])
    assert s.circulating == frozenset()
