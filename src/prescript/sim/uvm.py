"""UVM-style testbench parts: sequence item, sequence, driver, monitor, scoreboard, environment.

The names follow the Universal Verification Methodology so a verification engineer finds the
usual seams; the implementation is plain Python with no simulator kernel underneath (pyuvm
schedules through cocotb and an HDL simulator, which a plant model does not have).

- `LoadStep` (sequence item): one scenario — a heat step at a given facility-water temperature.
- `StepSequence`: constrained-random `LoadStep`s from a seed; the same seed gives the same runs.
- `Driver`: turns the item into boundary conditions on the time axis.
- `Monitor`: samples the plant and the controller into a `Trace`.
- `Scoreboard`: judges the trace and returns `Result`s with the closed status set.
- `Bench.run`: the environment — builds the parts, closes the loop and runs one item.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import numpy as np

from prescript.result import Result, Status, unrun
from prescript.sim import plant
from prescript.sim.pid import Pid
from prescript.sim.plant import Inputs, PlantParams

# Within this of 0 or 1 the command counts as pinned at a stroke end.
_EDGE = 1e-6

SUPPLY_SENSOR = "TT-HX01"  # secondary supply temperature, the controlled variable
VALVE = "CV-01"  # facility-side control valve


@dataclass(frozen=True)
class LoadStep:
    """Sequence item: the IT heat steps from `heat_before_kw` to `heat_after_kw` at `step_at_s`."""

    run: str
    heat_before_kw: float
    heat_after_kw: float
    step_at_s: float
    facility_c: float

    def describe(self) -> str:
        return (
            f"{self.run}: heat {self.heat_before_kw:.0f}->{self.heat_after_kw:.0f} kW "
            f"at t={self.step_at_s:.0f} s, facility water {self.facility_c:.1f} °C"
        )


@dataclass(frozen=True)
class Constraints:
    """The envelope a sequence draws from (inclusive ranges)."""

    heat_kw: tuple[float, float]
    facility_c: tuple[float, float]
    step_at_s: tuple[int, int]

    def __post_init__(self) -> None:
        for name in ("heat_kw", "facility_c", "step_at_s"):
            lo, hi = getattr(self, name)
            if lo > hi:
                raise ValueError(f"Constraints.{name}: {lo} > {hi}")


@dataclass(frozen=True)
class StepSequence:
    """Constrained-random sequence. Step times are whole controller samples."""

    constraints: Constraints
    seed: int
    runs: int

    def __iter__(self) -> Iterator[LoadStep]:
        rng = random.Random(self.seed)
        c = self.constraints
        for i in range(1, self.runs + 1):
            yield LoadStep(
                run=f"run-{i:02d}",
                heat_before_kw=round(rng.uniform(*c.heat_kw), 1),
                heat_after_kw=round(rng.uniform(*c.heat_kw), 1),
                step_at_s=float(rng.randint(*c.step_at_s)),
                facility_c=round(rng.uniform(*c.facility_c), 1),
            )


@dataclass(frozen=True)
class Driver:
    """Boundary conditions for one item. The step lands on a controller sample, never inside one."""

    item: LoadStep

    def inputs(self, t_s: float, valve_cmd: float) -> Inputs:
        heat = self.item.heat_after_kw if t_s >= self.item.step_at_s else self.item.heat_before_kw
        return Inputs(heat_kw=heat, facility_c=self.item.facility_c, valve_cmd=valve_cmd)


@dataclass(frozen=True)
class Sample:
    t_s: float
    heat_kw: float
    supply_c: float
    return_c: float
    valve: float  # actual position
    valve_cmd_raw: float  # controller output before the stroke clamp


@dataclass
class Monitor:
    samples: list[Sample] = field(default_factory=list)

    def sample(self, t_s: float, heat_kw: float, x: np.ndarray, pid: Pid) -> None:
        self.samples.append(
            Sample(t_s, heat_kw, float(x[1]), float(x[0]), float(x[2]), pid.output_raw)
        )


@dataclass(frozen=True)
class Criteria:
    """What the scoreboard holds the plant to."""

    setpoint_c: float
    band_k: float  # |supply - setpoint| must end within this
    settle_s: float  # ... no later than this after the step
    hold_s: float  # ... and the run must show it holding for at least this long


@dataclass(frozen=True)
class Scoreboard:
    criteria: Criteria

    def score(self, item: LoadStep, trace: list[Sample]) -> list[Result]:
        c = self.criteria
        judged_from = item.step_at_s + c.settle_s
        end = trace[-1].t_s if trace else 0.0
        if end - judged_from < c.hold_s:
            why = (
                f"the run ends at t={end:.0f} s; settling is judged from t={judged_from:.0f} s "
                f"and needs {c.hold_s:.0f} s of trace after that"
            )
            return [unrun("S-01", item.run, why), unrun("S-02", item.run, why)]
        return [self._settle(item, trace), self._valve_range(item, trace)]

    def _settle(self, item: LoadStep, trace: list[Sample]) -> Result:
        c = self.criteria
        after = [s for s in trace if s.t_s >= item.step_at_s]
        outside = [s for s in after if abs(s.supply_c - c.setpoint_c) > c.band_k]
        band = f"{c.setpoint_c:.1f}±{c.band_k:.1f} °C"
        method = f"method: {plant.METHOD}"
        if not outside:
            return Result(
                "S-01",
                item.run,
                Status.PASS,
                f"{SUPPLY_SENSOR} never left {band} after the step; {method}",
                subjects=(SUPPLY_SENSOR,),
            )
        last = outside[-1].t_s - item.step_at_s
        late = [s for s in outside if s.t_s > item.step_at_s + c.settle_s]
        if not late:
            return Result(
                "S-01",
                item.run,
                Status.PASS,
                f"{SUPPLY_SENSOR} back within {band} {last:.0f} s after the step "
                f"(limit {c.settle_s:.0f} s); {method}",
                subjects=(SUPPLY_SENSOR,),
            )
        worst = max(late, key=lambda s: abs(s.supply_c - c.setpoint_c))
        tail = (
            "still outside at the end of the run"
            if late[-1] is trace[-1]
            else (f"last outside {last:.0f} s after the step")
        )
        return Result(
            "S-01",
            item.run,
            Status.FAIL,
            f"{SUPPLY_SENSOR} outside {band} past the {c.settle_s:.0f} s limit, {tail}; {method}",
            subjects=(SUPPLY_SENSOR,),
            offending=(f"{SUPPLY_SENSOR} {worst.supply_c:.2f} °C at t={worst.t_s:.0f} s",),
        )

    def _valve_range(self, item: LoadStep, trace: list[Sample]) -> Result:
        c = self.criteria
        judged = [s for s in trace if s.t_s >= item.step_at_s + c.settle_s]
        bad_position = [s for s in trace if not -1e-9 <= s.valve <= 1.0 + 1e-9]
        # A command at either end of the stroke means the loop has no authority left: with the
        # valve pinned open the supply temperature is whatever the exchanger can manage.
        bad_command = [s for s in judged if not _EDGE < s.valve_cmd_raw < 1.0 - _EDGE]
        method = f"method: {plant.METHOD}"
        offending = []
        if bad_position:
            w = max(bad_position, key=lambda s: abs(s.valve - 0.5))
            offending.append(f"{VALVE} position {w.valve:.1%} at t={w.t_s:.0f} s")
        if bad_command:
            w = max(bad_command, key=lambda s: abs(s.valve_cmd_raw - 0.5))
            offending.append(
                f"{VALVE} command {w.valve_cmd_raw:.1%} at t={w.t_s:.0f} s "
                f"({len(bad_command)} samples at a stroke end once settled)"
            )
        if offending:
            return Result(
                "S-02",
                item.run,
                Status.FAIL,
                f"{VALVE} leaves no control margin once settled; {method}",
                subjects=(VALVE,),
                offending=tuple(offending),
            )
        lo = min(s.valve_cmd_raw for s in judged)
        hi = max(s.valve_cmd_raw for s in judged)
        peak = max(s.valve_cmd_raw for s in trace)
        transient = f", transient peak {peak:.0%} clamped" if peak > 1.0 else ""
        return Result(
            "S-02",
            item.run,
            Status.PASS,
            f"{VALVE} command {lo:.0%}-{hi:.0%} once settled{transient}; {method}",
            subjects=(VALVE,),
        )


@dataclass(frozen=True)
class Run:
    item: LoadStep
    trace: list[Sample]
    results: list[Result]


@dataclass(frozen=True)
class Bench:
    """The environment: plant, controller, sample time, run length and the scoreboard's criteria."""

    plant: PlantParams
    controller: Callable[[], Pid]
    criteria: Criteria
    dt_s: float
    duration_s: float

    def run(self, item: LoadStep) -> Run:
        c = self.criteria
        try:
            x = plant.steady_state(self.plant, item.heat_before_kw, c.setpoint_c, item.facility_c)
        except ValueError as exc:
            why = f"no steady state to start from: {exc}"
            return Run(item, [], [unrun("S-01", item.run, why), unrun("S-02", item.run, why)])
        pid = self.controller()
        pid.reset(output=float(x[2]), pv=float(x[1]))
        driver, monitor = Driver(item), Monitor()
        steps = round(self.duration_s / self.dt_s)
        cmd = float(x[2])
        for k in range(steps + 1):
            t = k * self.dt_s
            cmd = pid.update(c.setpoint_c, float(x[1]), self.dt_s) if k else cmd
            u = driver.inputs(t, cmd)
            monitor.sample(t, u.heat_kw, x, pid)
            if k < steps:
                x = plant.step(self.plant, u, x, self.dt_s)
        return Run(item, monitor.samples, Scoreboard(c).score(item, monitor.samples))
