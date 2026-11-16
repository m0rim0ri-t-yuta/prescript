"""Phase 1 testbench (#27): plant, controller, sequence, scoreboard and the `sim` command."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from typer.testing import CliRunner

from prescript.cli import app
from prescript.result import Status
from prescript.sim import plant, poc
from prescript.sim.pid import Pid
from prescript.sim.plant import Inputs, PlantParams
from prescript.sim.uvm import Constraints, LoadStep, StepSequence

runner = CliRunner()
P = poc.PLANT
SETPOINT = poc.CRITERIA.setpoint_c


def _statuses(item: LoadStep) -> dict[str, Status]:
    return {r.assertion: r.status for r in poc.BENCH.run(item).results}


# --- plant ---------------------------------------------------------------------------------------


def test_effectiveness_limits() -> None:
    assert plant.effectiveness(0.0, 0.5) == 0.0
    assert plant.effectiveness(1.0, 1.0) == pytest.approx(0.5)
    # Cr -> 0 is a condensing-like exchanger: 1 - exp(-NTU).
    assert plant.effectiveness(2.0, 0.0) == pytest.approx(1.0 - np.exp(-2.0))
    assert plant.effectiveness(2.0, 0.5) < plant.effectiveness(3.0, 0.5) < 1.0


def test_a_shut_valve_moves_no_heat() -> None:
    assert plant.exchanger_kw(P, 0.0, 50.0, 25.0) == 0.0


def test_steady_state_is_steady() -> None:
    x = plant.steady_state(P, 120.0, SETPOINT, 28.0)
    u = Inputs(heat_kw=120.0, facility_c=28.0, valve_cmd=float(x[2]))
    assert np.allclose(plant.derivatives(P, u, x), 0.0, atol=1e-9)
    assert x[0] == pytest.approx(SETPOINT + 120.0 / P.secondary_kw_k)


def test_capacity_is_where_the_valve_runs_out() -> None:
    cap = plant.capacity_kw(P, SETPOINT, 32.0)
    assert 0.99 < float(plant.steady_state(P, cap - 0.01, SETPOINT, 32.0)[2]) <= 1.0
    with pytest.raises(ValueError, match="exceeds the capacity"):
        plant.steady_state(P, cap + 1.0, SETPOINT, 32.0)


def test_plant_params_need_provenance() -> None:
    with pytest.raises(ValueError, match="provenance"):
        PlantParams(1, 1, 1, 1, 1, 1, 1, 1, provenance="")


# --- controller ----------------------------------------------------------------------------------


def test_pid_does_not_wind_up_against_a_stroke_end() -> None:
    pid = Pid(kp=0.1, ti_s=20.0)
    pid.reset(output=0.9, pv=SETPOINT)
    for _ in range(500):  # a supply 2 K hot that never comes down
        out = pid.update(SETPOINT, SETPOINT + 2.0, 1.0)
    assert out == 1.0
    assert pid.integral == pytest.approx(0.9)  # held where it was, not 500 samples of error
    # The moment the error goes, the valve comes off the end instead of staying pinned.
    assert pid.update(SETPOINT, SETPOINT - 0.1, 1.0) < 1.0


# --- sequence ------------------------------------------------------------------------------------


@given(seed=st.integers(min_value=0, max_value=2**32 - 1))
def test_a_seed_reproduces_its_runs_inside_the_envelope(seed: int) -> None:
    env = poc.ENVELOPE
    first, again = list(StepSequence(env, seed, 5)), list(StepSequence(env, seed, 5))
    assert first == again
    for item in first:
        assert env.heat_kw[0] <= item.heat_before_kw <= env.heat_kw[1]
        assert env.heat_kw[0] <= item.heat_after_kw <= env.heat_kw[1]
        assert env.facility_c[0] <= item.facility_c <= env.facility_c[1]
        assert item.step_at_s == int(item.step_at_s)


def test_constraints_reject_an_empty_range() -> None:
    with pytest.raises(ValueError, match="heat_kw"):
        Constraints(heat_kw=(150.0, 30.0), facility_c=(24.0, 32.0), step_at_s=(60, 180))


# --- scoreboard ----------------------------------------------------------------------------------


@settings(max_examples=40, deadline=None)
@given(
    before=st.floats(*poc.ENVELOPE.heat_kw),
    after=st.floats(*poc.ENVELOPE.heat_kw),
    water=st.floats(*poc.ENVELOPE.facility_c),
    step_at=st.integers(*poc.ENVELOPE.step_at_s),
)
def test_every_step_inside_the_envelope_passes(
    before: float, after: float, water: float, step_at: int
) -> None:
    """The design claim the testbench exists to check: within 150 kW and 24-32 °C, it holds."""
    item = LoadStep("h", before, after, float(step_at), water)
    assert _statuses(item) == {"S-01": Status.PASS, "S-02": Status.PASS}


def test_a_step_past_the_capacity_fails_both_with_evidence() -> None:
    item = LoadStep("over", 100.0, 200.0, 100.0, 32.0)  # capacity at 32 °C is ~177 kW
    results = {r.assertion: r for r in poc.BENCH.run(item).results}
    settle, valve = results["S-01"], results["S-02"]
    assert settle.status is Status.FAIL and valve.status is Status.FAIL
    assert settle.offending[0].startswith("TT-HX01 ")
    assert valve.offending[0].startswith("CV-01 command 100.0%")
    assert "still outside at the end of the run" in settle.detail


def test_every_result_names_the_method() -> None:
    for item in (
        LoadStep("ok", 50.0, 120.0, 100.0, 28.0),
        LoadStep("x", 100.0, 200.0, 100.0, 32.0),
    ):
        for r in poc.BENCH.run(item).results:
            assert plant.METHOD in r.detail


def test_a_run_too_short_to_judge_is_unrun() -> None:
    item = LoadStep("late", 50.0, 100.0, 700.0, 28.0)  # judged from t=1000 s, run ends at 900 s
    assert _statuses(item) == {"S-01": Status.UNRUN, "S-02": Status.UNRUN}


def test_a_start_past_the_capacity_is_unrun_not_pass() -> None:
    results = poc.BENCH.run(LoadStep("hot-start", 200.0, 100.0, 100.0, 32.0)).results
    assert {r.status for r in results} == {Status.UNRUN}
    assert all("no steady state to start from" in r.detail for r in results)


def test_a_settle_inside_the_limit_reports_how_long_it_took() -> None:
    [settle, _] = poc.BENCH.run(LoadStep("ok", 30.0, 150.0, 100.0, 32.0)).results
    assert settle.status is Status.PASS
    assert "s after the step (limit 300 s)" in settle.detail


# --- command line --------------------------------------------------------------------------------


def test_sim_inside_the_envelope_exits_zero() -> None:
    res = runner.invoke(app, ["sim", "--seed", "1", "--runs", "6"])
    assert res.exit_code == 0, res.output
    assert "PASS 12 · FAIL 0 · WARN 0 · UNRUN 0" in res.output


def test_sim_past_the_capacity_exits_one_and_shows_the_evidence() -> None:
    res = runner.invoke(app, ["sim", "--seed", "1", "--runs", "8", "--max-heat-kw", "260"])
    assert res.exit_code == 1, res.output
    assert "FAIL   S-01@run-07" in res.output
    assert "         - CV-01 command 100.0%" in res.output


def test_sim_rejects_an_envelope_upside_down() -> None:
    res = runner.invoke(app, ["sim", "--max-heat-kw", "10"])
    assert res.exit_code == 2
