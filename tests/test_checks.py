"""Each routine shows PASS, FAIL and (where reachable) UNRUN — verification-semantics.md §8."""

from __future__ import annotations

from typing import Any

import pytest

from prescript import engine
from prescript.checks.balance import METHOD as BALANCE_METHOD
from prescript.checks.balance import balance
from prescript.checks.completeness import completeness
from prescript.checks.dual_path import dual_path
from prescript.checks.inlet_temp import inlet_temp
from prescript.checks.loading import loading
from prescript.checks.loop_closed import loop_closed
from prescript.checks.n_minus_1 import n_minus_1
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


# --- n_minus_1 ------------------------------------------------------------------

SWEEP = ["cdu", "pump", "header", "manifold"]


def test_n_minus_1_pass_in_normal(design: Design) -> None:
    """2N CDUs with N+1 pumps: no single element the sweep stops costs a rack its loop."""
    r = n_minus_1(design, _state(design), _a("n_minus_1", sweep=SWEEP))
    assert r.status is Status.PASS
    assert "8 it_liquid loads keep a closed loop with any one of 24 elements stopped" in r.detail
    assert "MAN-A-01" in r.subjects
    assert "PMP-A-2" not in r.subjects  # the standby pump carries no flow, so nothing to drop


def test_n_minus_1_fails_when_the_surviving_cdu_is_the_last_one(design: Design) -> None:
    """Maintenance has used the redundancy up: stopping CDU-B now takes the whole hall."""
    r = n_minus_1(design, _state(design, "maint-cdu-A"), _a("n_minus_1", sweep=["cdu"]))
    assert r.status is Status.FAIL
    assert r.detail == "stopping CDU-B leaves 8/8 it_liquid loads without a closed loop"
    assert r.offending == (
        "CDU-B: RACK-01, RACK-02, RACK-03, RACK-04, RACK-05, RACK-06, RACK-07, RACK-08",
    )


def test_n_minus_1_names_every_single_point_of_failure(doc: dict[str, Any]) -> None:
    """With RACK-03 fed from side A alone, each A-side element upstream of it becomes single."""
    doc["modes"]["normal"]["overrides"] = {"V-SB-03": "closed"}
    d = parse_design(doc)
    r = n_minus_1(d, _state(d), _a("n_minus_1", sweep=SWEEP))
    assert r.status is Status.FAIL
    assert r.detail == "5/23 elements leave it_liquid loads without a closed loop"
    assert r.offending == (
        "CDU-A: RACK-03",
        "HDR-R-A: RACK-03",
        "HDR-S-A: RACK-03",
        "MAN-A-03: RACK-03",
        "PMP-A-1: RACK-03",
    )


def test_n_minus_1_sweeps_only_what_carries_flow(design: Design) -> None:
    """In pump-fail-A the standby of side A is running and the duty pump is the dead one."""
    r = n_minus_1(design, _state(design, "pump-fail-A"), _a("n_minus_1", sweep=["pump"]))
    assert r.status is Status.PASS
    assert r.subjects == ("PMP-A-2", "PMP-B-1")


def test_n_minus_1_unrun_without_mode(design: Design) -> None:
    assert n_minus_1(design, None, _a("n_minus_1")).status is Status.UNRUN


def test_n_minus_1_unrun_when_nothing_carries_flow(design: Design) -> None:
    r = n_minus_1(design, _state(design, "facility-loss"), _a("n_minus_1", sweep=["cdu"]))
    assert r.status is Status.UNRUN
    assert r.detail == "nothing of kind cdu carries flow here"


def test_n_minus_1_unrun_for_empty_class(design: Design) -> None:
    r = n_minus_1(design, _state(design), _a("n_minus_1", **{"class": "nope"}))
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


# --- balance --------------------------------------------------------------------


def test_balance_pass_in_normal(design: Design) -> None:
    r = balance(design, _state(design), _a("balance", tolerance_pct=10))
    assert r.status is Status.PASS
    assert "8 it_liquid loads within 10% of their required flow, worst 0%" in r.detail
    assert BALANCE_METHOD in r.detail  # a screening method says so (verification-semantics §6)


def test_balance_pass_with_one_branch_shut(design: Design) -> None:
    """valve-shut-01 exists for this check: RACK-01 takes its whole 227 L/min through MAN-B-01."""
    r = balance(design, _state(design, "valve-shut-01"), _a("balance", tolerance_pct=10))
    assert r.status is Status.PASS


def test_balance_fails_when_the_surviving_branch_is_too_small(doc: dict[str, Any]) -> None:
    """A 150 L/min manifold is enough for half a rack, not for the whole of one."""
    doc["blocks"]["rack_gb200_nvl72"]["params"]["manifold_lpm"] = 150
    d = parse_design(doc)
    r = balance(d, _state(d, "valve-shut-01"), _a("balance", tolerance_pct=10))
    assert r.status is Status.FAIL
    assert r.offending == ("RACK-01 227 L/min required, 150 L/min available (-34%)",)


def test_balance_counts_every_load_an_element_carries(doc: dict[str, Any]) -> None:
    """Each side carries 998.6 L/min (racks + half the RDHX) against 600: 227 * 600/998.6."""
    doc["blocks"]["cdu_loop"]["params"]["rating_lpm"] = 600
    d = parse_design(doc)
    r = balance(d, _state(d), _a("balance", tolerance_pct=10))
    assert r.status is Status.FAIL
    assert len(r.offending) == 8
    assert r.offending[0] == "RACK-01 227 L/min required, 136 L/min available (-40%)"


def test_balance_pass_when_a_class_draws_nothing(doc: dict[str, Any]) -> None:
    """Zero demand means zero required flow; it must not divide by it."""
    doc["modes"]["normal"]["demand"]["it_liquid"] = 0.0
    d = parse_design(doc)
    assert balance(d, _state(d), _a("balance")).status is Status.PASS


def test_balance_unrun_without_mode(design: Design) -> None:
    assert balance(design, None, _a("balance")).status is Status.UNRUN


def test_balance_unrun_when_a_rating_is_null(doc: dict[str, Any]) -> None:
    doc["blocks"]["cdu_loop"]["params"]["rating_lpm"] = None
    d = parse_design(doc)
    r = balance(d, _state(d), _a("balance"))
    assert r.status is Status.UNRUN
    assert "CDU-A.rating_lpm" in r.missing


def test_balance_unrun_when_nothing_circulates(design: Design) -> None:
    r = balance(design, _state(design, "facility-loss"), _a("balance"))
    assert r.status is Status.UNRUN
    assert r.detail == "no loads are circulating"


def test_balance_unrun_for_empty_class(design: Design) -> None:
    r = balance(design, _state(design), _a("balance", **{"class": "nope"}))
    assert r.status is Status.UNRUN


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
    c13 = [r for r in results if r.assertion == "C-13"]  # consistency, still a W3 routine
    assert c13 and all(r.status is Status.UNRUN for r in c13)


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


def test_every_unrun_in_the_reference_is_an_unbuilt_routine(design: Design) -> None:
    """An assertion is not asked for in a mode where it could never leave UNRUN (#15)."""
    unrun = [r for r in engine.run(design) if r.status is Status.UNRUN]
    assert unrun and all("not implemented" in r.detail for r in unrun)


def test_fail_without_evidence_is_impossible() -> None:
    with pytest.raises(ValueError, match="offending"):
        Result("X", "normal", Status.FAIL, "no evidence")


def test_pass_with_missing_data_is_impossible() -> None:
    with pytest.raises(ValueError, match="missing"):
        Result("X", "normal", Status.PASS, "ok", missing=("A.rating_lpm",))
