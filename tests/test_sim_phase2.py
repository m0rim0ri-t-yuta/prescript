"""Phase 2 testbench (#45): the plant built from the netlist, its scoreboard and the CLI."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from prescript import modes
from prescript.cli import app
from prescript.ir import Design
from prescript.loader import load_design
from prescript.result import Status
from prescript.sim import mvp, network, thermal
from prescript.sim.netbench import Bench, Event, Profile, Scenario, ScenarioSequence, events_from

REF = Path(__file__).resolve().parents[1] / "examples" / "gb200-1su" / "netlist.yaml"
runner = CliRunner()

STOP_A = (
    Event(30, {"PMP-A-2": "off"}, "stop-A@s1"),
    Event(60, {"PMP-A-1": "off"}, "stop-A@s2"),
    Event(120, {"CDU-A": "off"}, "stop-A@s3"),
    Event(180, {"V-PMP-A-1": "closed", "V-PMP-A-2": "closed"}, "stop-A@s4"),
)


def _variant(tmp_path: Path, edit: Callable[[str], str]) -> Design:
    text = edit(REF.read_text(encoding="utf-8"))
    path = tmp_path / "netlist.yaml"
    path.write_text(text, encoding="utf-8")
    return load_design(path)


def _solve(design: Design, mode: str) -> tuple[network.Network, network.Solution]:
    net = network.build(design)
    st = modes.resolve(design, design.modes[mode])
    valve = {k: 1.0 if v == "open" else 0.0 for k, v in st.device_state.items()}
    speed = {}
    for pump in design.nodes_of("pump"):
        cdu = next(e.src for e in design.incoming(pump.id))
        on = st.node_state[pump.id] == "on" and st.node_state[cdu] == "on"
        speed[pump.id] = 1.0 if on else 0.0
    return net, network.solve(net, network.Operating(valve, speed))


def _scenario(events: tuple[Event, ...] = (), duration: float = 300.0) -> Scenario:
    return Scenario("run-t", "normal", events, Profile.flat(1.0), Profile.flat(20.0), duration)


def _statuses(design: Design, sc: Scenario) -> dict[str, Status]:
    return {r.assertion: r.status for r in Bench(design, mvp.CONTROLS).run(sc).results}


@pytest.fixture(scope="module")
def ref() -> Design:
    return load_design(REF)


# --- hydraulics ----------------------------------------------------------------------------------


def test_flow_is_conserved_and_symmetric(ref: Design) -> None:
    _, sol = _solve(ref, "normal")
    assert sol.converged
    loads = sum(sol.flow[n.id] for n in ref.nodes.values() if n.kind in {"rack", "rdhx"})
    cdus = sol.flow["CDU-A"] + sol.flow["CDU-B"]
    assert loads == pytest.approx(cdus, rel=1e-6)
    assert sol.flow["CDU-A"] == pytest.approx(sol.flow["CDU-B"], rel=1e-6)
    assert sol.flow["RACK-01"] == pytest.approx(sol.flow["RACK-08"], rel=1e-6)


def test_a_stopped_pump_carries_nothing_either_way(ref: Design) -> None:
    _, sol = _solve(ref, "pump-fail-A")
    assert sol.flow["PMP-A-1"] == 0.0
    assert sol.flow["PMP-A-2"] > 1000.0


def test_one_cdu_carries_the_hall_when_the_other_stops(ref: Design) -> None:
    _, normal = _solve(ref, "normal")
    _, maint = _solve(ref, "maint-cdu-A")
    assert maint.flow["CDU-A"] == 0.0
    assert maint.flow["CDU-B"] > normal.flow["CDU-B"]


def test_pump_curve_meets_its_rated_point(ref: Design) -> None:
    net = network.build(ref)
    op = network.Operating(valve={}, speed={"PMP-A-1": 1.0})
    drop, _ = network._drop(net, net.element("PMP-A-1"), 2300.0, op)
    assert -drop == pytest.approx(250.0, abs=0.1)  # rating_kpa at rating_lpm


def test_a_loop_without_an_expansion_tank_has_no_pressure(tmp_path: Path) -> None:
    design = _variant(tmp_path, lambda s: s.replace("fill_kpa: 100,", "fill_kpa: null,"))
    _, sol = _solve(design, "normal")
    assert sol.converged
    assert np.isnan(sol.pressure).all()
    assert sol.flow["CDU-A"] > 1000.0  # it still circulates


# --- heat ----------------------------------------------------------------------------------------


def test_exchanger_meets_its_rated_point(ref: Design) -> None:
    th = thermal.build(network.build(ref))
    cdu = ref.nodes["CDU-A"]
    c = ref.fluids["pg25"].volumetric_heat_kj_lk()
    assert c is not None
    c_sec = float(cdu.get("rating_lpm")) / 60.0 * c
    q = float(cdu.get("rating_kw"))
    # rated: supply = facility + approach, return = supply + Q / C_sec
    duty = th.exchangers["CDU-A"].kappa(c_sec, 1.0) * (float(cdu.get("approach_k")) + q / c_sec)
    assert duty == pytest.approx(q, rel=1e-9)


def test_heat_in_equals_heat_out_once_settled(ref: Design) -> None:
    run = Bench(ref, mvp.CONTROLS).run(_scenario(duration=60.0))
    assert run.trace is not None
    tr = run.trace
    bench = Bench(ref, mvp.CONTROLS)
    k = len(tr.t) - 1
    sol = network.Solution(
        flow=dict(zip(tr.elements, tr.flow[k], strict=True)),
        pressure=tr.pressure[k],
        pressurised=~np.isnan(tr.pressure[k]),
        converged=True,
    )
    out = sum(
        thermal.exchanger_kw(bench.th, sol, tr.temps[k], c, tr.fac_valve[k][c], tr.facility_c[k])
        for c in ("CDU-A", "CDU-B")
    )
    assert out == pytest.approx(tr.heat_kw[k], rel=0.01)


# --- scoreboard ----------------------------------------------------------------------------------


def test_reference_stop_sequence_passes_cavitation_and_inlet(ref: Design) -> None:
    got = _statuses(ref, _scenario(STOP_A, duration=600.0))
    assert got["P-01"] is Status.PASS
    assert got["P-02"] is Status.PASS


def test_low_tank_pressure_cavitates_only_once_one_pump_carries_the_hall(tmp_path: Path) -> None:
    design = _variant(tmp_path, lambda s: s.replace("fill_kpa: 100,", "fill_kpa: 10,"))
    assert _statuses(design, _scenario())["P-01"] is Status.PASS
    run = Bench(design, mvp.CONTROLS).run(_scenario(STOP_A, duration=600.0))
    p01 = next(r for r in run.results if r.assertion == "P-01")
    assert p01.status is Status.FAIL
    assert any("PMP-B-1" in o and "stop-A@s2" in o for o in p01.offending)


def test_a_rack_cut_off_on_both_sides_overheats(ref: Design) -> None:
    cut = (Event(10, {"V-SA-01": "closed", "V-SB-01": "closed"}, "cut"),)
    run = Bench(ref, mvp.CONTROLS).run(_scenario(cut, duration=120.0))
    p02 = next(r for r in run.results if r.assertion == "P-02")
    assert p02.status is Status.FAIL
    assert any(o.startswith("RACK-01 stagnant coolant") for o in p02.offending)


def test_surge_screen_is_unrun_without_an_event_and_never_fails(ref: Design) -> None:
    assert _statuses(ref, _scenario())["P-03"] is Status.UNRUN
    # stopping a duty pump: the instantaneous bound does not clear, so it asks for a study
    assert _statuses(ref, _scenario(STOP_A, duration=300.0))["P-03"] is Status.WARN


def test_surge_screen_passes_when_the_bound_clears(tmp_path: Path) -> None:
    design = _variant(tmp_path, lambda s: s.replace("wave_speed_m_s: 1200,", "wave_speed_m_s: 50,"))
    assert _statuses(design, _scenario(STOP_A, duration=300.0))["P-03"] is Status.PASS


def test_a_null_the_plant_needs_makes_every_check_unrun(tmp_path: Path) -> None:
    design = _variant(tmp_path, lambda s: s.replace("shutoff_kpa: 320,", "shutoff_kpa: null,"))
    run = Bench(design, mvp.CONTROLS).run(_scenario())
    assert {r.status for r in run.results} == {Status.UNRUN}
    assert "PMP-A-1.shutoff_kpa" in run.results[0].detail


def test_npshr_missing_is_unrun_not_pass(tmp_path: Path) -> None:
    design = _variant(tmp_path, lambda s: s.replace("npshr_m: 3,", "npshr_m: null,"))
    run = Bench(design, mvp.CONTROLS).run(_scenario())
    p01 = next(r for r in run.results if r.assertion == "P-01")
    assert p01.status is Status.UNRUN
    assert "PMP-A-1.npshr_m" in p01.missing


# --- sequence ------------------------------------------------------------------------------------


def test_sequence_is_reproducible_and_run_00_is_nominal(ref: Design) -> None:
    a = list(ScenarioSequence(ref, "normal", STOP_A, mvp.ENVELOPE, seed=3, runs=3))
    b = list(ScenarioSequence(ref, "normal", STOP_A, mvp.ENVELOPE, seed=3, runs=3))
    assert a == b
    assert [e.at_s for e in a[0].events] == [30, 60, 120, 180]
    assert a[0].it_factor == Profile.flat(1.0)
    for sc in a[1:]:
        times = [e.at_s for e in sc.events]
        assert times == sorted(times)
        assert [e.label for e in sc.events] == [e.label for e in STOP_A]


# --- cli -----------------------------------------------------------------------------------------


def test_cli_runs_phase_2_and_writes_trace_and_plot(tmp_path: Path) -> None:
    csv, svg = tmp_path / "trace.csv", tmp_path / "trace.svg"
    res = runner.invoke(
        app, ["sim", str(REF), "--runs", "1", "--trace", str(csv), "--plot", str(svg)]
    )
    assert res.exit_code == 0, res.output
    assert "Phase 2 testbench" in res.output
    assert csv.read_text(encoding="utf-8").startswith("t_s,state,")
    assert svg.read_text(encoding="utf-8").startswith("<svg")


def test_cli_rejects_an_unknown_mode_and_phase_2_options_without_a_netlist() -> None:
    assert runner.invoke(app, ["sim", str(REF), "--mode", "nope"]).exit_code == 2
    assert runner.invoke(app, ["sim", "--mode", "normal"]).exit_code == 2


# --- procedures on the time axis (#44 -> #45) ----------------------------------------------------


def test_a_procedure_becomes_events_at_its_cumulative_times(ref: Design) -> None:
    events = events_from(ref, "stop-cdu-A")
    steps = ref.procedures["stop-cdu-A"].steps
    assert [e.set for e in events] == [s.set for s in steps]
    t, want = 0.0, []
    for s in steps:
        assert s.after_s is not None
        t += s.after_s
        want.append(t)
    assert [e.at_s for e in events] == want
    assert events[1].label == "stop-cdu-A@s2: Stop the duty pump"


def test_events_need_a_known_procedure_and_after_s(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown procedure"):
        events_from(load_design(REF), "nope")
    design = _variant(tmp_path, lambda s: s.replace("after_s: 30", "within_s: 30", 1))
    with pytest.raises(ValueError, match="needs after_s"):
        events_from(design, "stop-cdu-A")


def test_cli_plays_a_procedure_and_names_the_step_that_breaks(tmp_path: Path) -> None:
    ok = runner.invoke(app, ["sim", str(REF), "-p", "stop-cdu-A", "--runs", "0"])
    assert ok.exit_code == 0, ok.output
    assert "stop-cdu-A@s2: Stop the duty pump" in ok.output
    low = tmp_path / "low.yaml"
    low.write_text(
        REF.read_text(encoding="utf-8").replace("fill_kpa: 100,", "fill_kpa: 10,"),
        encoding="utf-8",
    )
    bad = runner.invoke(app, ["sim", str(low), "-p", "stop-cdu-A", "--runs", "0"])
    assert bad.exit_code == 1, bad.output
    assert "FAIL   P-01@run-00" in bad.output
    assert runner.invoke(app, ["sim", str(REF), "-p", "nope"]).exit_code == 2
    assert (
        runner.invoke(app, ["sim", str(REF), "-p", "stop-cdu-A", "-m", "summer-peak"]).exit_code
        == 2
    )
    assert runner.invoke(app, ["sim", "-p", "stop-cdu-A"]).exit_code == 2
