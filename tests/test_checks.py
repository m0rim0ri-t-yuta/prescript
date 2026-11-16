"""Each routine shows PASS, FAIL and (where reachable) UNRUN — verification-semantics.md §8."""

from __future__ import annotations

import re
from typing import Any

import pytest

from prescript import engine
from prescript.checks.balance import METHOD as BALANCE_METHOD
from prescript.checks.balance import balance
from prescript.checks.completeness import completeness
from prescript.checks.consistency import consistency
from prescript.checks.dual_path import dual_path
from prescript.checks.inlet_temp import inlet_temp
from prescript.checks.leak_isolation import METHOD as LEAK_METHOD
from prescript.checks.leak_isolation import leak_isolation, zone
from prescript.checks.loading import loading
from prescript.checks.loop_closed import loop_closed
from prescript.checks.n_minus_1 import n_minus_1
from prescript.checks.pressure_drop import METHOD as PRESSURE_METHOD
from prescript.checks.pressure_drop import _Inputs, _pipe_kpa, pressure_drop
from prescript.checks.return_temp import METHOD as RETURN_METHOD
from prescript.checks.return_temp import return_temp
from prescript.checks.ride_through import METHOD as RIDE_METHOD
from prescript.checks.ride_through import ride_through
from prescript.ir import Assertion, Design, Fluid, Node
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


# --- leak_isolation -------------------------------------------------------------


def test_leak_isolation_zone_of_a_rack_is_its_branch(design: Design) -> None:
    """No valve between the manifolds and the rack, so they leak and are isolated together."""
    inside, boundary = zone(design, "RACK-01")
    assert inside == {"MAN-A-01", "MAN-B-01", "RACK-01"}
    assert sorted(e.via.id for e in boundary if e.via) == [
        "V-RA-01",
        "V-RB-01",
        "V-SA-01",
        "V-SB-01",
    ]


@pytest.mark.parametrize("mode", ["normal", "maint-cdu-A", "maint-cdu-B"])
def test_leak_isolation_pass_for_every_rack(design: Design, mode: str) -> None:
    r = leak_isolation(design, _state(design, mode), _a("leak_isolation"))
    assert r.status is Status.PASS, r.offending
    assert r.detail == (
        "8 it_liquid loads can each be valved off (up to 4 valves) without stopping any of "
        f"9 running loads; {LEAK_METHOD}"
    )


def test_leak_isolation_fails_when_a_manifold_takes_its_rack_down(design: Design) -> None:
    r = leak_isolation(design, _state(design), _a("leak_isolation", sweep=["manifold"]))
    assert r.status is Status.FAIL
    assert len(r.offending) == 16
    assert "MAN-A-01: stops RACK-01" in r.offending


def test_leak_isolation_fails_when_no_valve_separates_the_cdu(design: Design) -> None:
    r = leak_isolation(design, _state(design), _a("leak_isolation", sweep=["header"]))
    assert r.status is Status.FAIL
    assert r.offending == (
        "HDR-R-A: no valve between it and CDU-A",
        "HDR-R-B: no valve between it and CDU-B",
    )


def test_leak_isolation_counts_the_other_side_as_collateral(design: Design) -> None:
    """With CDU-A down, shutting the B supply header's ring stops the whole hall."""
    r = leak_isolation(
        design, _state(design, "maint-cdu-A"), _a("leak_isolation", sweep=["header"])
    )
    assert r.status is Status.FAIL
    assert any(o.startswith("HDR-S-B: stops RACK-01, ") and "RDHX-01" in o for o in r.offending)


def test_leak_isolation_fails_when_a_shared_branch_has_no_valves(doc: dict[str, Any]) -> None:
    """Two racks behind one valve ring: a leak on either stops both."""
    doc["edges"].append({"from": "MAN-A-01", "to": "RACK-02"})
    d = parse_design(doc)
    r = leak_isolation(d, _state(d), _a("leak_isolation"))
    assert r.status is Status.FAIL
    assert r.offending == ("RACK-01: stops RACK-02", "RACK-02: stops RACK-01")


def test_leak_isolation_a_check_valve_does_not_bound_a_zone(doc: dict[str, Any]) -> None:
    edges = doc["edges"]
    edges.append(
        {"from": "MAN-A-01", "to": "RACK-02", "via": {"id": "CV-1", "kind": "check_valve"}}
    )
    d = parse_design(doc)
    assert "RACK-02" in zone(d, "RACK-01")[0]


def test_leak_isolation_unrun_without_mode(design: Design) -> None:
    assert leak_isolation(design, None, _a("leak_isolation")).status is Status.UNRUN


def test_leak_isolation_unrun_when_nothing_runs(design: Design) -> None:
    r = leak_isolation(design, _state(design, "facility-loss"), _a("leak_isolation"))
    assert r.status is Status.UNRUN
    assert "no load has a closed loop" in r.detail


def test_leak_isolation_unrun_for_empty_class(design: Design) -> None:
    r = leak_isolation(design, _state(design), _a("leak_isolation", **{"class": "nope"}))
    assert r.status is Status.UNRUN
    assert r.detail == "nothing to sweep: no nope loads"


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


# --- pressure_drop --------------------------------------------------------------


def test_pressure_drop_header_matches_darcy_weisbach_by_hand() -> None:
    """998.6 L/min in DN150 PG25: v 0.942 m/s, Re 72756, f 0.0205; (f*30/0.15 + 5) * rho v^2/2."""
    header = Node(
        id="H",
        kind="header",
        attrs={"dn_mm": 150, "length_m": 30, "roughness_mm": 0.045, "k_fittings": 5},
    )
    fluid = Fluid(name="pg25", cp_kj_kgk=3.85, density_kg_l=1.03, viscosity_mpas=2.0)
    assert _pipe_kpa(header, 998.6, fluid, _Inputs()) == pytest.approx(4.16, abs=0.01)


def test_pressure_drop_pass_in_normal(design: Design) -> None:
    """RACK-01: 20.2 kPa up a supply leg, 97.4 across the rack, 5.5 down a return: 123/250."""
    r = pressure_drop(design, _state(design), _a("pressure_drop"))
    assert r.status is Status.PASS
    assert r.detail.startswith("9 loops within the available head, worst 49%")
    assert PRESSURE_METHOD in r.detail  # a screening method says so (verification-semantics §6)


def test_pressure_drop_fails_when_the_headers_are_too_narrow(doc: dict[str, Any]) -> None:
    """The bore now matters: DN80 headers cost the pump more head than it has."""
    doc["blocks"]["cdu_loop"]["params"]["dn_mm"] = 80
    d = parse_design(doc)
    r = pressure_drop(d, _state(d), _a("pressure_drop"))
    assert r.status is Status.FAIL
    assert r.offending[0] == "RACK-01 via PMP-A-1: 256/250 kPa (102%)"


def test_pressure_drop_fails_after_a_rack_refresh(doc: dict[str, Any]) -> None:
    """The roadmap demo: at 200 kW the rack whose A branch is shut pushes all of it through B."""
    doc["blocks"]["rack_gb200_nvl72"]["params"]["heat_kw"] = 200
    d = parse_design(doc)
    r = pressure_drop(d, _state(d, "valve-shut-01"), _a("pressure_drop"))
    assert r.status is Status.FAIL
    assert r.offending == ("RACK-01 via PMP-B-1: 253/250 kPa (101%)",)


def test_pressure_drop_available_kpa_overrides_the_pump(design: Design) -> None:
    r = pressure_drop(design, _state(design), _a("pressure_drop", available_kpa=100))
    assert r.status is Status.FAIL
    assert r.offending[0] == "RACK-01 via available_kpa: 123/100 kPa (123%)"


def test_pressure_drop_unrun_when_the_pump_head_is_null(doc: dict[str, Any]) -> None:
    doc["blocks"]["cdu_loop"]["params"]["head_kpa"] = None
    d = parse_design(doc)
    r = pressure_drop(d, _state(d), _a("pressure_drop"))
    assert r.status is Status.UNRUN
    assert "PMP-A-1.rating_kpa" in r.missing


def test_pressure_drop_unrun_without_viscosity(doc: dict[str, Any]) -> None:
    doc["fluids"]["pg25"]["viscosity_mpas"] = None
    d = parse_design(doc)
    r = pressure_drop(d, _state(d), _a("pressure_drop"))
    assert r.status is Status.UNRUN
    assert r.missing == ("fluid pg25.viscosity_mpas",)


def test_pressure_drop_unrun_for_an_unknown_method(design: Design) -> None:
    r = pressure_drop(design, _state(design), _a("pressure_drop", method="hazen_williams"))
    assert r.status is Status.UNRUN


def test_pressure_drop_unrun_when_nothing_circulates(design: Design) -> None:
    r = pressure_drop(design, _state(design, "facility-loss"), _a("pressure_drop"))
    assert r.status is Status.UNRUN


def test_pressure_drop_unrun_without_mode(design: Design) -> None:
    assert pressure_drop(design, None, _a("pressure_drop")).status is Status.UNRUN


# --- return_temp ----------------------------------------------------------------


def test_return_temp_pass_in_normal(design: Design) -> None:
    """20 C facility + 3 K approach + 10 K across every load: 33 C back at both CDUs."""
    r = return_temp(design, _state(design), _a("return_temp", kinds=["cdu"]))
    assert r.status is Status.PASS
    assert "2 cdus see a mixed return inside their range, warmest 33.0 C" in r.detail
    assert RETURN_METHOD in r.detail  # a screening method says so (verification-semantics §6)


def test_return_temp_fails_above_the_range(doc: dict[str, Any]) -> None:
    doc["blocks"]["cdu_loop"]["params"]["return_max_c"] = 40
    d = parse_design(doc)
    r = return_temp(d, _state(d, "summer-peak"), _a("return_temp"))
    assert r.status is Status.FAIL
    assert r.offending == (
        "CDU-A mixed return 45.0 C > 40.0 C",
        "CDU-B mixed return 45.0 C > 40.0 C",
    )


def test_return_temp_fails_below_the_range(doc: dict[str, Any]) -> None:
    doc["blocks"]["cdu_loop"]["params"]["return_min_c"] = 35
    d = parse_design(doc)
    r = return_temp(d, _state(d), _a("return_temp"))
    assert r.status is Status.FAIL
    assert r.offending[0] == "CDU-A mixed return 33.0 C < 35.0 C"


@pytest.mark.parametrize(("ceiling", "status"), [(45.4, Status.FAIL), (45.5, Status.PASS)])
def test_return_temp_weights_by_flow(doc: dict[str, Any], ceiling: float, status: Status) -> None:
    """RDHX at dT 20 K sends half the flow at 55 C; mixed with the racks' 45 C that is 45.48 C.

    A plain average of the two outlets would be 50 C, and of the nine loads 46.1 C.
    """
    rdhx = doc["nodes"][-1]
    assert rdhx["id"] == "RDHX-01"
    rdhx["delta_t_k"] = 20
    doc["blocks"]["cdu_loop"]["params"]["return_max_c"] = ceiling
    d = parse_design(doc)
    assert return_temp(d, _state(d, "summer-peak"), _a("return_temp")).status is status


def test_return_temp_judges_only_the_cdu_that_runs(design: Design) -> None:
    r = return_temp(design, _state(design, "maint-cdu-A"), _a("return_temp"))
    assert r.status is Status.PASS
    assert r.subjects == ("CDU-B",)


def test_return_temp_unrun_when_the_range_is_null(doc: dict[str, Any]) -> None:
    doc["blocks"]["cdu_loop"]["params"]["return_max_c"] = None
    d = parse_design(doc)
    r = return_temp(d, _state(d), _a("return_temp"))
    assert r.status is Status.UNRUN
    assert r.missing == ("CDU-A.return_max_c", "CDU-B.return_max_c")


def test_return_temp_unrun_without_the_facility_condition(doc: dict[str, Any]) -> None:
    doc["modes"]["normal"]["conditions"] = {}
    d = parse_design(doc)
    r = return_temp(d, _state(d), _a("return_temp"))
    assert r.status is Status.UNRUN
    assert r.missing == ("mode normal.conditions.facility_supply_c",)


def test_return_temp_unrun_when_nothing_circulates(design: Design) -> None:
    r = return_temp(design, _state(design, "facility-loss"), _a("return_temp"))
    assert r.status is Status.UNRUN


def test_return_temp_unrun_without_mode(design: Design) -> None:
    assert return_temp(design, None, _a("return_temp")).status is Status.UNRUN


# --- ride_through ---------------------------------------------------------------


def _ride(design: Design, **args: Any) -> Result:
    a = _a("ride_through", must_exceed_s=60, **args)
    return ride_through(design, _state(design, "facility-loss"), a)


def _seconds(r: Result) -> int:
    """The time a ride_through result quotes, for comparing two designs."""
    match = re.search(r"for (\d+) s", r.detail)
    assert match, r.detail
    return int(match.group(1))


def test_ride_through_pass_in_facility_loss(design: Design) -> None:
    r = _ride(design)
    assert r.status is Status.PASS
    assert r.subjects == ("RACK-01",)  # one connected inventory serves the whole hall
    assert RIDE_METHOD in r.detail
    assert _seconds(r) > 60


def test_ride_through_fails_on_a_loop_with_too_little_water(doc: dict[str, Any]) -> None:
    doc["blocks"]["cdu_loop"]["params"].update(cdu_volume_l=1, pump_volume_l=1, header_m=0.1)
    doc["blocks"]["rack_gb200_nvl72"]["params"].update(manifold_volume_l=1, rack_volume_l=1)
    r = _ride(parse_design(doc))
    assert r.status is Status.FAIL
    assert r.offending and r.offending[0].startswith("RACK-01's loop: ")
    assert "s < 60 s" in r.offending[0]


def test_ride_through_unrun_without_the_loop_starting_temperature(doc: dict[str, Any]) -> None:
    del doc["modes"]["facility-loss"]["conditions"]["loop_start_c"]
    r = _ride(parse_design(doc))
    assert r.status is Status.UNRUN
    assert r.missing == ("mode facility-loss.conditions.loop_start_c",)


def test_ride_through_unrun_when_an_inventory_is_null(doc: dict[str, Any]) -> None:
    doc["blocks"]["rack_gb200_nvl72"]["params"]["rack_volume_l"] = None
    r = _ride(parse_design(doc))
    assert r.status is Status.UNRUN
    assert "RACK-01.volume_l" in r.missing


def test_ride_through_unrun_without_a_time_to_beat(design: Design) -> None:
    a = Assertion(id="T", check="ride_through", args={}, modes=("facility-loss",))
    r = ride_through(design, _state(design, "facility-loss"), a)
    assert r.status is Status.UNRUN
    assert r.missing == ("T.must_exceed_s",)


def test_ride_through_takes_every_class_heat_but_its_own_limit(doc: dict[str, Any]) -> None:
    """The rear doors heat the same water; the limit still comes from the class under test."""
    quiet = _ride(parse_design(doc))
    doc["modes"]["facility-loss"]["demand"]["it_air"] = 1.0
    loud = _ride(parse_design(doc))
    assert "RACK-01 at 45 C" in loud.detail  # not the rear door's 40 C
    assert _seconds(loud) < _seconds(quiet)


def test_ride_through_stops_at_a_shut_valve(doc: dict[str, Any], design: Design) -> None:
    """A rack isolated on both sides rides on what is left inside its own branch, and no more."""
    doc["modes"]["facility-loss"]["overrides"].update(
        {"V-SA-01": "closed", "V-SB-01": "closed", "V-RA-01": "closed", "V-RB-01": "closed"}
    )
    r = _ride(parse_design(doc))
    assert r.subjects == ("RACK-01", "RACK-02")  # the isolated rack, and the rest of the hall
    assert _seconds(r) < _seconds(_ride(design))


# --- consistency ----------------------------------------------------------------


def _spec_check(design: Design, against: str = "02_Loads") -> Result:
    a = _a("consistency", against=against, fields=["heat_kw", "delta_t_k", "max_inlet_c"])
    return consistency(design, None, a)


def test_consistency_pass_on_the_reference(design: Design) -> None:
    r = _spec_check(design)
    assert r.status is Status.PASS
    assert len(r.subjects) == 9
    assert "02_Loads" in r.detail


def test_consistency_catches_a_block_parameter_edit(doc: dict[str, Any]) -> None:
    """The W4 demo: one parameter moves eight racks, and only the schedule notices."""
    doc["blocks"]["rack_gb200_nvl72"]["params"]["heat_kw"] = 200
    r = _spec_check(parse_design(doc))
    assert r.status is Status.FAIL
    assert len(r.offending) == 8
    assert r.offending[0] == "RACK-01.heat_kw: netlist 200, 02_Loads 150"


def test_consistency_reports_a_row_the_netlist_does_not_have(doc: dict[str, Any]) -> None:
    doc["spec"]["02_Loads"]["rows"].append(
        {"id": "RACK-09", "heat_kw": 150, "delta_t_k": 10, "max_inlet_c": 45}
    )
    r = _spec_check(parse_design(doc))
    assert r.status is Status.FAIL
    assert r.offending == ("RACK-09: in 02_Loads, not in the netlist",)


def test_consistency_unrun_when_a_cell_is_undecided(doc: dict[str, Any]) -> None:
    doc["spec"]["02_Loads"]["rows"][0]["heat_kw"] = None
    r = _spec_check(parse_design(doc))
    assert r.status is Status.UNRUN
    assert r.missing == ("spec 02_Loads.RACK-01.heat_kw",)


def test_consistency_unrun_without_the_table(design: Design) -> None:
    r = _spec_check(design, against="99_Nope")
    assert r.status is Status.UNRUN
    assert r.missing == ("spec.99_Nope",)


def test_consistency_still_fails_when_another_cell_cannot_be_compared(doc: dict[str, Any]) -> None:
    """A proven disagreement is not hidden by an unanswered question; both are reported."""
    doc["blocks"]["rack_gb200_nvl72"]["params"]["heat_kw"] = 200
    doc["spec"]["02_Loads"]["rows"][1]["max_inlet_c"] = None
    r = _spec_check(parse_design(doc))
    assert r.status is Status.FAIL
    assert r.missing == ("spec 02_Loads.RACK-02.max_inlet_c",)
    assert any(o.startswith("RACK-02.heat_kw") for o in r.offending)


# --- completeness: null never passes -------------------------------------------


def test_completeness_reports_null_ratings(doc: dict[str, Any]) -> None:
    doc["blocks"]["rack_gb200_nvl72"]["params"]["branch_kv"] = None
    design = parse_design(doc)
    r = completeness(design, None, _a("completeness", kinds=["valve"]))
    assert r.status is Status.FAIL
    assert "V-SA-01.kv_m3h" in r.offending


def test_completeness_pass_when_rated(design: Design) -> None:
    r = completeness(design, None, _a("completeness", kinds=["manifold"]))
    assert r.status is Status.PASS


def test_completeness_unrun_for_unknown_kind(design: Design) -> None:
    assert completeness(design, None, _a("completeness", kinds=["x"])).status is Status.UNRUN


# --- engine-level invariants -----------------------------------------------------


def test_not_implemented_never_passes(doc: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Every named routine is built now, so a planned one is made up here; the rule still holds."""
    monkeypatch.setattr(engine, "PLANNED", frozenset({"future_check"}))
    doc["assertions"].append({"id": "Z-00", "check": "future_check", "modes": ["normal"]})
    r = _result(engine.run(parse_design(doc)), "Z-00", "normal")
    assert r.status is Status.UNRUN and r.detail == "not implemented"


def test_unknown_check_is_unrun(doc: dict[str, Any]) -> None:
    doc["assertions"].append({"id": "Z-01", "check": "made_up", "modes": ["normal"]})
    r = _result(engine.run(parse_design(doc)), "Z-01", "normal")
    assert r.status is Status.UNRUN and "unknown check" in r.detail


def test_severity_warn_downgrades_fail_only(doc: dict[str, Any]) -> None:
    doc["blocks"]["rack_gb200_nvl72"]["params"]["branch_kv"] = None  # C-14 now has nulls to find
    results = engine.run(parse_design(doc))
    assert _result(results, "C-14", "static").status is Status.WARN
    assert _result(results, "C-15", "meta").status is Status.WARN


def test_reference_design_has_no_fail(design: Design) -> None:
    results = engine.run(design)
    assert [r for r in results if r.status is Status.FAIL] == []
    assert _result(results, "C-03", "maint-cdu-A").status is Status.PASS


def test_every_unrun_in_the_reference_is_an_unbuilt_routine(design: Design) -> None:
    """An assertion is not asked for in a mode where it could never leave UNRUN (#15).

    The reference names only built routines now, so this list is empty. The assertion still
    guards the property: an UNRUN that appears here for any other reason is a bug.
    """
    unrun = [r for r in engine.run(design) if r.status is Status.UNRUN]
    assert all("not implemented" in r.detail for r in unrun)


def test_fail_without_evidence_is_impossible() -> None:
    with pytest.raises(ValueError, match="offending"):
        Result("X", "normal", Status.FAIL, "no evidence")


def test_pass_with_missing_data_is_impossible() -> None:
    with pytest.raises(ValueError, match="missing"):
        Result("X", "normal", Status.PASS, "ok", missing=("A.rating_lpm",))
