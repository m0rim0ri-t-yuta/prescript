from __future__ import annotations

from prescript.ir import Design
from prescript.modes import resolve


def test_normal_energizes_both_sides(design: Design) -> None:
    s = resolve(design, design.modes["normal"])
    assert {"DP-A", "DP-B", "RACK-01", "EM-BUS"} <= s.energized
    assert "GEN-01" not in s.energized


def test_maint_a_takes_side_a_down(design: Design) -> None:
    s = resolve(design, design.modes["maint-A"])
    assert "UPSOUT-A" not in s.energized
    assert "DP-B" in s.energized


def test_generator_mode_runs_on_battery_and_generator(design: Design) -> None:
    s = resolve(design, design.modes["generator"])
    assert "LVMSB-A" not in s.energized  # utility lost
    assert {"UPSOUT-A", "UPSOUT-B", "EM-BUS"} <= s.energized
    assert s.ats_selection["ATS-01"] == "GEN-01"


def test_open_tie_does_not_conduct(design: Design) -> None:
    s = resolve(design, design.modes["normal"])
    tie = next(e for e in design.edges if e.via is not None and e.via.id == "TIE-AB")
    assert not s.conducts(tie)
    closed = resolve(design, design.modes["tie-closed"])
    assert closed.conducts(tie)
