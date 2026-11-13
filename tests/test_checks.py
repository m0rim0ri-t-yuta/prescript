"""Each routine shows PASS, FAIL and (where reachable) UNRUN — verification-semantics.md §8."""

from __future__ import annotations

from typing import Any

import pytest

from prescript import engine
from prescript.checks.completeness import completeness
from prescript.checks.dual_path import dual_path
from prescript.checks.inlet_temp import inlet_temp
from prescript.checks.loading import loading
from prescript.checks.loop_closed import loop_closed
from prescript.ir import Assertion, Design
from prescript.loader import parse_design
from prescript.modes import resolve
from prescript.result import Result, Status


def _a(check: str, **args: Any) -> Assertion:
    return Assertion(id="T", check=check, args=args, modes=("normal",))


def _state(design: Design, mode: str = "normal") -> Any:
    return resolve(design, design.modes[mode])


def _result(results: list[Result], aid: str, mode: str) -> Result:
    return next(r for r in results if r.assertion == aid and r.mode == mode)


# --- loop_closed ----------------------------------------------------------------


def test_loop_closed_pass_in_normal(design: Design) -> None:
    r = loop_closed(design, _state(design), _a("loop_closed"))
    assert r.status is Status.PASS
    assert "RACK-08" in r.subjects


def test_loop_closed_fails_when_a_rack_cannot_return(doc: dict[str, Any]) -> None:
    """Supplied but isolated on both return legs: a path that cannot return is not a path."""
    doc["modes"]["normal"]["overrides"] = {"V-RA-03": "closed", "V-RB-03": "closed"}
    d = parse_design(doc)
    r = loop_closed(d, _state(d), _a("loop_closed"))
    assert r.status is Status.FAIL
    assert r.offending == ("RACK-03 (no return path)",)


def test_loop_closed_fails_when_a_rack_has_no_supply(doc: dict[str, Any]) -> None:
    doc["modes"]["normal"]["overrides"] = {"V-SA-03": "closed", "V-SB-03": "closed"}
    d = parse_design(doc)
    r = loop_closed(d, _state(d), _a("loop_closed"))
    assert r.status is Status.FAIL
    assert r.offending == ("RACK-03 (no supply)",)


def test_loop_closed_via_demands_a_named_node_on_the_loop(design: Design) -> None:
    a = _a("loop_closed", via="CDU-A")
    assert loop_closed(design, _state(design), a).status is Status.PASS
    r = loop_closed(design, _state(design, "maint-cdu-A"), a)
    assert r.status is Status.FAIL
    assert r.offending[0] == "RACK-01 (loop does not pass CDU-A)"


def test_loop_closed_unrun_without_mode(design: Design) -> None:
    assert loop_closed(design, None, _a("loop_closed")).status is Status.UNRUN


def test_loop_closed_unrun_for_empty_class(design: Design) -> None:
    r = loop_closed(design, _state(design), _a("loop_closed", **{"class": "nope"}))
    assert r.status is Status.UNRUN


# --- dual_path ------------------------------------------------------------------


def test_dual_path_pass_in_normal(design: Design) -> None:
    r = dual_path(design, _state(design), _a("dual_path"))
    assert r.status is Status.PASS


def test_dual_path_fails_when_a_rack_branch_is_shut(design: Design) -> None:
    r = dual_path(design, _state(design, "valve-shut-01"), _a("dual_path"))
    assert r.status is Status.FAIL
    assert r.offending == ("RACK-01 (no live side A)",)


def test_dual_path_unrun_without_mode(design: Design) -> None:
    assert dual_path(design, None, _a("dual_path")).status is Status.UNRUN


# --- loading --------------------------------------------------------------------


def test_loading_flow_matches_the_sensible_heat_balance(design: Design) -> None:
    """150 kW at dT 10 K in PG25 is 150 * 60 / (3.85 * 1.03 * 10) = 227 L/min per rack."""
    r = loading(design, _state(design), _a("loading", basis="flow", kinds=["manifold"]))
    assert r.status is Status.PASS
    # Each rack is dual-fed, so one manifold carries half of 227 L/min against a 300 L/min rating.
    assert "worst 38%" in r.detail


def test_loading_heat_on_the_cdu(design: Design) -> None:
    r = loading(design, _state(design, "maint-cdu-A"), _a("loading", basis="heat", kinds=["cdu"]))
    assert r.status is Status.PASS
    assert "worst 88%" in r.detail  # 8 x 150 kW + 120 kW on a 1500 kW CDU


def test_loading_fails_after_a_rack_refresh(doc: dict[str, Any]) -> None:
    """The roadmap demo: 150 kW -> 200 kW racks overload the surviving CDU in maintenance."""
    doc["blocks"]["rack_gb200_nvl72"]["params"]["heat_kw"] = 200
    d = parse_design(doc)
    r = loading(
        d,
        _state(d, "maint-cdu-A"),
        _a("loading", basis="flow", kinds=["cdu", "manifold"], limit=1.0),
    )
    assert r.status is Status.FAIL
    assert r.offending[0] == "CDU-B 2602/2300 L/min (113%)"
    assert "MAN-B-01 303/300 L/min (101%)" in r.offending


def test_loading_unrun_when_a_rating_is_null(doc: dict[str, Any]) -> None:
    doc["blocks"]["cdu_loop"]["params"]["rating_lpm"] = None
    d = parse_design(doc)
    r = loading(d, _state(d), _a("loading", basis="flow", kinds=["cdu"]))
    assert r.status is Status.UNRUN
    assert "CDU-A.rating_lpm" in r.missing


def test_loading_unrun_when_a_load_input_is_null(doc: dict[str, Any]) -> None:
    doc["blocks"]["rack_gb200_nvl72"]["params"]["delta_t_k"] = None
    d = parse_design(doc)
    r = loading(d, _state(d), _a("loading", basis="flow", kinds=["cdu"]))
    assert r.status is Status.UNRUN
    assert "RACK-01.delta_t_k" in r.missing


# --- inlet_temp -----------------------------------------------------------------


def test_inlet_temp_pass_at_design_supply(design: Design) -> None:
    r = inlet_temp(design, _state(design, "summer-peak"), _a("inlet_temp"))
    assert r.status is Status.PASS  # 32 C facility + 3 K approach against a 45 C limit


def test_inlet_temp_fails_when_the_facility_runs_warm(doc: dict[str, Any]) -> None:
    doc["modes"]["normal"]["conditions"]["facility_supply_c"] = 50
    d = parse_design(doc)
    r = inlet_temp(d, _state(d), _a("inlet_temp"))
    assert r.status is Status.FAIL
    assert r.offending[0] == "RACK-01 inlet 53 C > 45 C"


def test_inlet_temp_unrun_without_the_facility_condition(doc: dict[str, Any]) -> None:
    doc["modes"]["normal"]["conditions"] = {}
    d = parse_design(doc)
    r = inlet_temp(d, _state(d), _a("inlet_temp"))
    assert r.status is Status.UNRUN
    assert r.missing == ("mode normal.conditions.facility_supply_c",)


# --- completeness: null never passes -------------------------------------------


def test_completeness_reports_null_ratings(design: Design) -> None:
    r = completeness(design, None, _a("completeness", kinds=["valve"]))
    assert r.status is Status.FAIL
    assert "V-SA-01.kv_m3h" in r.offending


def test_completeness_pass_when_rated(design: Design) -> None:
    r = completeness(design, None, _a("completeness", kinds=["manifold"]))
    assert r.status is Status.PASS


def test_completeness_unrun_for_unknown_kind(design: Design) -> None:
    assert completeness(design, None, _a("completeness", kinds=["x"])).status is Status.UNRUN


# --- engine-level invariants -----------------------------------------------------


def test_not_implemented_never_passes(design: Design) -> None:
    results = engine.run(design)
    c08 = [r for r in results if r.assertion == "C-08"]
    assert c08 and all(r.status is Status.UNRUN for r in c08)


def test_unknown_check_is_unrun(doc: dict[str, Any]) -> None:
    doc["assertions"].append({"id": "Z-01", "check": "made_up", "modes": ["normal"]})
    r = _result(engine.run(parse_design(doc)), "Z-01", "normal")
    assert r.status is Status.UNRUN and "unknown check" in r.detail


def test_severity_warn_downgrades_fail_only(design: Design) -> None:
    results = engine.run(design)
    assert _result(results, "C-14", "static").status is Status.WARN
    assert _result(results, "C-15", "meta").status is Status.WARN


def test_reference_design_has_no_fail(design: Design) -> None:
    results = engine.run(design)
    assert [r for r in results if r.status is Status.FAIL] == []
    assert _result(results, "C-03", "maint-cdu-A").status is Status.PASS


def test_fail_without_evidence_is_impossible() -> None:
    with pytest.raises(ValueError, match="offending"):
        Result("X", "normal", Status.FAIL, "no evidence")


def test_pass_with_missing_data_is_impossible() -> None:
    with pytest.raises(ValueError, match="missing"):
        Result("X", "normal", Status.PASS, "ok", missing=("A.rating_lpm",))
