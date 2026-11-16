"""Phase 2 testbench (#45): the plant is built from the netlist, not written by hand.

The device under test is the whole technology cooling loop of a netlist — every CDU, pump, header,
manifold, rack and valve in it — as `network` (hydraulics) and `thermal` (heat) describe. The UVM
roles are the ones Phase 1 uses:

- `Event`: one state transition on the time axis — the `set:` of a procedure step (an ASM state),
  applied at a time.
- `Scenario` (sequence item): a starting mode, the events, an IT-load profile and a facility-water
  profile.
- `ScenarioSequence`: run-00 is the nominal scenario as written; the rest are constrained random —
  the step times jittered, the IT load and the facility water moving inside an envelope.
- `Plant`: the netlist's actuators (valve strokes, pump speed ramps, one PI loop per running CDU on
  its facility-water valve) around the network and heat models.
- `Monitor` / `Trace`: everything sampled once per controller period.
- `Scoreboard`: cavitation (P-01), load inlet temperature (P-02), surge screening (P-03).
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from prescript import modes
from prescript.ir import LOAD_KINDS, Design
from prescript.result import Result, Status, unrun
from prescript.sim import network, thermal
from prescript.sim.network import Network, NetworkError, Operating, Solution
from prescript.sim.pid import Pid
from prescript.sim.thermal import Boundary, Thermal

P_ATM_KPA = 101.325
G = 9.80665
_STOPPED = 0.02  # a pump below this fraction of speed with nothing asking it to run has stopped
_FLOWING = 1.0  # L/min; below this a branch counts as stagnant

METHOD = f"{network.METHOD}; {thermal.METHOD}"


# ----------------------------------------------------------------------------- stimulus ---


@dataclass(frozen=True)
class Event:
    """A state transition: `set` (node states and valve positions) applied at `at_s`."""

    at_s: float
    set: dict[str, str]
    label: str


@dataclass(frozen=True)
class Profile:
    """Piecewise-linear in time; flat before the first point and after the last."""

    points: tuple[tuple[float, float], ...]

    def at(self, t_s: float) -> float:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return float(np.interp(t_s, xs, ys))

    @staticmethod
    def flat(value: float) -> Profile:
        return Profile(((0.0, value),))


@dataclass(frozen=True)
class Scenario:
    run: str
    mode: str
    events: tuple[Event, ...]
    it_factor: Profile  # multiplies every load's heat, on top of the mode's demand factor
    facility_c: Profile  # facility-water supply temperature
    duration_s: float

    def describe(self) -> str:
        it = [v for _, v in self.it_factor.points]
        fac = [v for _, v in self.facility_c.points]
        times = ", ".join(f"{e.at_s:.0f}" for e in self.events)
        when = f"events at t={times} s" if times else "no events"
        return (
            f"from {self.mode}, {when}, IT {min(it):.0%}-{max(it):.0%}, "
            f"facility water {min(fac):.1f}-{max(fac):.1f} °C"
        )


@dataclass(frozen=True)
class Envelope:
    """What the random runs draw from (inclusive ranges)."""

    step_jitter: tuple[float, float]  # multiplies each gap between events
    it_factor: tuple[float, float]
    it_hold_s: tuple[int, int]  # how long the IT load holds before it moves
    facility_offset_k: tuple[float, float]  # around the mode's facility_supply_c
    settle_s: float  # run on after the last event

    def __post_init__(self) -> None:
        for name in ("step_jitter", "it_factor", "it_hold_s", "facility_offset_k"):
            lo, hi = getattr(self, name)
            if lo > hi:
                raise ValueError(f"Envelope.{name}: {lo} > {hi}")


@dataclass(frozen=True)
class ScenarioSequence:
    design: Design
    mode: str
    events: tuple[Event, ...]
    envelope: Envelope
    seed: int
    runs: int  # random runs after the nominal run-00

    def __iter__(self) -> Iterator[Scenario]:
        env = self.envelope
        facility = float(self.design.modes[self.mode].conditions.get("facility_supply_c", 20.0))
        end = (self.events[-1].at_s if self.events else 0.0) + env.settle_s
        yield Scenario(
            "run-00",
            self.mode,
            self.events,
            Profile.flat(1.0),
            Profile.flat(facility),
            end,
        )
        rng = random.Random(self.seed)
        for i in range(1, self.runs + 1):
            events, t, last = [], 0.0, 0.0
            for e in self.events:
                t += (e.at_s - last) * rng.uniform(*env.step_jitter)
                last = e.at_s
                events.append(Event(round(t), e.set, e.label))
            end = (events[-1].at_s if events else 0.0) + env.settle_s
            it_points, t = [(0.0, round(rng.uniform(*env.it_factor), 2))], 0.0
            while t < end:
                t += rng.randint(*env.it_hold_s)
                it_points.append((t, it_points[-1][1]))
                it_points.append((t + 30.0, round(rng.uniform(*env.it_factor), 2)))
            fac = (
                (0.0, round(facility + rng.uniform(*env.facility_offset_k), 1)),
                (end, round(facility + rng.uniform(*env.facility_offset_k), 1)),
            )
            yield Scenario(
                f"run-{i:02d}",
                self.mode,
                tuple(events),
                Profile(tuple(it_points)),
                Profile(fac),
                end,
            )


# -------------------------------------------------------------------------------- plant ---


@dataclass(frozen=True)
class Controls:
    """The testbench's controller and sampling constants (not part of the design)."""

    kp: float  # facility valve stroke per K of supply error
    ti_s: float
    valve_tau_s: float  # facility valve actuator
    dt_s: float
    warmup_s: float  # run unrecorded from the starting mode until the loops have settled
    settled_k: float  # ... and no node may still move more than this over the last minute


class Plant:
    """The netlist's actuators around the network and heat models."""

    def __init__(self, design: Design, net: Network, th: Thermal, controls: Controls) -> None:
        self.design, self.net, self.th, self.ctl = design, net, th, controls
        self.cdu_of = {
            p.id: next(e.src for e in design.incoming(p.id) if design.nodes[e.src].kind == "cdu")
            for p in design.nodes_of("pump")
        }

    def start(self, mode: str) -> State:
        st = modes.resolve(self.design, self.design.modes[mode])
        node_state = dict(st.node_state)
        target = dict(st.device_state)
        state = State(
            node_state=node_state,
            target=target,
            valve={k: 1.0 if v == "open" else 0.0 for k, v in target.items()},
            speed={p: 1.0 if self._asked(node_state, p) else 0.0 for p in self.cdu_of},
            fac_valve={c.id: 0.5 for c in self.design.nodes_of("cdu")},
            pid={c.id: self._pid() for c in self.design.nodes_of("cdu")},
            temps=np.full(len(self.th.nodes), self._setpoint(self.design.nodes_of("cdu")[0].id)),
            demand=dict(st.demand),
        )
        for cdu, pid in state.pid.items():
            pid.reset(output=0.5, pv=self._setpoint(cdu))
        return state

    def _pid(self) -> Pid:
        return Pid(kp=self.ctl.kp, ti_s=self.ctl.ti_s)

    def _setpoint(self, cdu: str) -> float:
        value = self.design.nodes[cdu].get("supply_c")
        return float(value) if value is not None else 30.0

    def _asked(self, node_state: dict[str, str], pump: str) -> bool:
        return node_state.get(pump) == "on" and node_state.get(self.cdu_of[pump]) == "on"

    def apply(self, state: State, event: Event) -> None:
        for target, value in event.set.items():
            if target in state.node_state:
                state.node_state[target] = value
            else:
                state.target[target] = value

    def actuate(self, state: State, dt: float) -> None:
        """Move valves toward their targets and pumps toward their speed, over `dt`."""
        devices = self.design.devices()
        for vid, want in state.target.items():
            goal = 1.0 if want == "open" else 0.0
            stroke = devices[vid].attrs.get("stroke_s")
            if stroke is None or float(stroke) <= 0.0:
                state.valve[vid] = goal
            else:
                rate = dt / float(stroke)
                now = state.valve[vid]
                state.valve[vid] = min(goal, now + rate) if goal > now else max(goal, now - rate)
        for pump in self.cdu_of:
            goal = 1.0 if self._asked(state.node_state, pump) else 0.0
            ramp = self.design.nodes[pump].get("ramp_s")
            if ramp is None or float(ramp) <= 0.0:
                state.speed[pump] = goal
            else:
                now = state.speed[pump]
                state.speed[pump] = goal + (now - goal) * math.exp(-dt / float(ramp))
            if goal == 0.0 and state.speed[pump] < _STOPPED:
                state.speed[pump] = 0.0

    def operating(self, state: State) -> Operating:
        return Operating(valve=dict(state.valve), speed=dict(state.speed))

    def running_cdus(self, state: State) -> list[str]:
        return [c.id for c in self.design.nodes_of("cdu") if state.node_state[c.id] == "on"]

    def heat(self, state: State, factor: float) -> dict[str, float]:
        out = {}
        for node in self.design.nodes.values():
            if node.kind not in LOAD_KINDS or state.node_state.get(node.id) == "off":
                continue
            kw = node.get("heat_kw")
            if kw is None:
                continue
            out[node.id] = float(kw) * state.demand.get(str(node.get("class")), 1.0) * factor
        return out

    def control(self, state: State, sol: Solution, dt: float) -> None:
        temps = state.temps
        for cdu in self.running_cdus(state):
            pv = float(temps[self.th.nodes.index(cdu)])
            cmd = state.pid[cdu].update(self._setpoint(cdu), pv, dt)
            alpha = 1.0 - math.exp(-dt / self.ctl.valve_tau_s)
            state.fac_valve[cdu] += alpha * (cmd - state.fac_valve[cdu])

    def boundary(self, state: State, scenario: Scenario, t: float) -> Boundary:
        return Boundary(
            heat_kw=self.heat(state, scenario.it_factor.at(t)),
            facility_c=scenario.facility_c.at(t),
            cdu_valve={c: state.fac_valve[c] for c in self.running_cdus(state)},
        )


@dataclass
class State:
    node_state: dict[str, str]
    target: dict[str, str]  # valve id -> "open" | "closed"
    valve: dict[str, float]  # stroke 0..1
    speed: dict[str, float]  # pump speed 0..1
    fac_valve: dict[str, float]  # CDU id -> facility valve position
    pid: dict[str, Pid]
    temps: NDArray[np.float64]
    demand: dict[str, float]


# ------------------------------------------------------------------------------ monitor ---


@dataclass
class Trace:
    nodes: list[str]
    elements: list[str]
    junctions: list[str]
    t: list[float] = field(default_factory=list)
    label: list[str] = field(default_factory=list)
    temps: list[NDArray[np.float64]] = field(default_factory=list)  # per node
    jtemps: list[NDArray[np.float64]] = field(default_factory=list)  # per junction
    flow: list[NDArray[np.float64]] = field(default_factory=list)  # per element, L/min
    pressure: list[NDArray[np.float64]] = field(default_factory=list)  # per junction, kPa gauge
    speed: list[dict[str, float]] = field(default_factory=list)
    fac_valve: list[dict[str, float]] = field(default_factory=list)
    heat_kw: list[float] = field(default_factory=list)
    facility_c: list[float] = field(default_factory=list)

    def series(self, element: str) -> NDArray[np.float64]:
        i = self.elements.index(element)
        return np.array([f[i] for f in self.flow])


class Monitor:
    def __init__(self, th: Thermal) -> None:
        net = th.net
        self.trace = Trace(list(th.nodes), [e.id for e in net.elements], list(net.junctions))
        self.th = th

    def sample(self, t: float, label: str, state: State, sol: Solution, u: Boundary) -> None:
        tr = self.trace
        tr.t.append(t)
        tr.label.append(label)
        tr.temps.append(state.temps.copy())
        tr.jtemps.append(thermal.junction_temps(self.th, sol, state.temps))
        tr.flow.append(np.array([sol.flow[e] for e in tr.elements]))
        tr.pressure.append(sol.pressure.copy())
        tr.speed.append(dict(state.speed))
        tr.fac_valve.append(dict(state.fac_valve))
        tr.heat_kw.append(sum(u.heat_kw.values()))
        tr.facility_c.append(u.facility_c)


# --------------------------------------------------------------------------- scoreboard ---


def vapour_kpa(t_c: float) -> float:
    """Vapour pressure of water (Antoine, 1-100 °C). PG25's is lower, so this is conservative."""
    return float(10.0 ** (8.07131 - 1730.63 / (233.426 + t_c)) * 0.133322)


def npsh(net: Network, tr: Trace, k: int, pump: str) -> tuple[float, float] | None:
    """(available, required) NPSH in metres at sample `k`, or None where it cannot be judged."""
    node = net.design.nodes[pump]
    npshr, at = node.get("npshr_m"), node.get("rating_lpm")
    rho = (net.fluid.density_kg_l or 0.0) * 1000.0
    e = net.element(pump)
    p = float(tr.pressure[k][e.a])
    q = float(tr.flow[k][tr.elements.index(pump)])
    if npshr is None or not at or math.isnan(p) or rho <= 0.0 or q <= _FLOWING:
        return None
    need = float(npshr) * max(1.0, (q / float(at)) ** 2)
    have = (p + P_ATM_KPA - vapour_kpa(float(tr.jtemps[k][e.a]))) * 1000.0 / (rho * G)
    return have, need


def load_temp(net: Network, tr: Trace, k: int, load: str) -> tuple[float, str]:
    """The coolant temperature a load sees: its inlet, or what it holds when nothing flows."""
    e = net.element(load)
    q = float(tr.flow[k][tr.elements.index(load)])
    if abs(q) > _FLOWING:
        return float(tr.jtemps[k][e.a if q > 0 else e.b]), "inlet"
    return float(tr.temps[k][tr.nodes.index(load)]), "stagnant coolant"


@dataclass(frozen=True)
class Scoreboard:
    design: Design
    net: Network
    th: Thermal

    def score(self, sc: Scenario, tr: Trace) -> list[Result]:
        return [self.cavitation(sc, tr), self.inlet(sc, tr), self.surge(sc, tr)]

    def _at(self, tr: Trace, k: int) -> str:
        return f"t={tr.t[k]:.0f} s ({tr.label[k]})"

    def cavitation(self, sc: Scenario, tr: Trace) -> Result:
        """P-01: NPSH available at every running pump's suction stays above what it requires."""
        missing: set[str] = set()
        worst: tuple[float, str] | None = None
        offending: list[str] = []
        for pump in self.design.nodes_of("pump"):
            e = self.net.element(pump.id)
            i = tr.elements.index(pump.id)
            ran = [k for k in range(len(tr.t)) if tr.flow[k][i] > _FLOWING]
            if not ran:
                continue
            for key in ("npshr_m", "rating_lpm"):
                if pump.get(key) is None:
                    missing.add(f"{pump.id}.{key}")
            if self.net.fluid.density_kg_l is None:
                missing.add(f"fluid {self.net.fluid.name}.density_kg_l")
            if any(math.isnan(float(tr.pressure[k][e.a])) for k in ran):
                missing.add(f"expansion tank (CDU fill_kpa) on the loop of {pump.id}")
            if missing:
                continue
            first_bad: str | None = None
            for k in ran:
                judged = npsh(self.net, tr, k, pump.id)
                if judged is None:
                    continue
                have, need = judged
                p, q = float(tr.pressure[k][e.a]), float(tr.flow[k][i])
                margin = have - need
                if worst is None or margin < worst[0]:
                    worst = (margin, f"{pump.id} {have:.1f} m vs {need:.1f} m at {self._at(tr, k)}")
                if margin < 0.0 and first_bad is None:
                    first_bad = (
                        f"{pump.id} NPSHa {have:.1f} m < NPSHr {need:.1f} m at "
                        f"{q:.0f} L/min, suction {p:.0f} kPa(g), {self._at(tr, k)}"
                    )
            if first_bad:
                offending.append(first_bad)
        method = (
            "method: NPSHa from the network's suction pressure and water vapour pressure "
            "(Antoine); NPSHr at the rated flow, scaled with (Q/Qr)^2 above it"
        )
        if missing:
            return unrun("P-01", sc.run, f"cavitation not judged; {method}", tuple(sorted(missing)))
        if offending:
            return Result(
                "P-01",
                sc.run,
                Status.FAIL,
                f"pump suction below the NPSH the pump requires; {method}",
                subjects=tuple(p.id for p in self.design.nodes_of("pump")),
                offending=tuple(offending),
            )
        if worst is None:
            return unrun("P-01", sc.run, f"no pump ran in this run; {method}")
        return Result("P-01", sc.run, Status.PASS, f"least margin: {worst[1]}; {method}")

    def inlet(self, sc: Scenario, tr: Trace) -> Result:
        """P-02: the coolant a load sees never exceeds its `max_inlet_c`."""
        missing: list[str] = []
        offending: list[str] = []
        worst: tuple[float, str] | None = None
        for node in self.design.nodes.values():
            if node.kind not in LOAD_KINDS:
                continue
            limit = node.get("max_inlet_c")
            if limit is None:
                missing.append(f"{node.id}.max_inlet_c")
                continue
            first_bad: str | None = None
            for k in range(len(tr.t)):
                temp, what = load_temp(self.net, tr, k, node.id)
                margin = float(limit) - temp
                if worst is None or margin < worst[0]:
                    worst = (margin, f"{node.id} {what} {temp:.1f} °C at {self._at(tr, k)}")
                if margin < 0.0 and first_bad is None:
                    first_bad = (
                        f"{node.id} {what} {temp:.1f} °C > {float(limit):.0f} °C at "
                        f"{self._at(tr, k)}"
                    )
            if first_bad:
                offending.append(first_bad)
        method = f"method: {thermal.METHOD}"
        if missing:
            return unrun("P-02", sc.run, f"inlet temperature not judged; {method}", tuple(missing))
        if offending:
            return Result(
                "P-02",
                sc.run,
                Status.FAIL,
                f"coolant above a load's maximum inlet temperature; {method}",
                subjects=tuple(n.id for n in self.design.nodes.values() if n.kind in LOAD_KINDS),
                offending=tuple(offending),
            )
        assert worst is not None
        return Result("P-02", sc.run, Status.PASS, f"hottest: {worst[1]}; {method}")

    def surge(self, sc: Scenario, tr: Trace) -> Result:
        """P-03: a Joukowsky bound on each header for every event — a screen, never a FAIL.

        The pressure change of an instantaneous velocity change is `rho * a * dv`; nothing slower
        exceeds it while the pressure stays above vapour pressure. So: if the bound keeps every
        header inside its design pressure and above vapour pressure, PASS; if not, WARN — a
        transient (method of characteristics) study is needed, not a verdict from this model.
        """
        method = (
            "method: Joukowsky bound rho*a*dv on each header's velocity change over each event, "
            "added to the quasi-steady pressure; pipes without a bore in the netlist are not "
            "screened"
        )
        if not sc.events:
            return unrun("P-03", sc.run, f"no event in this run to screen; {method}")
        rho = (self.net.fluid.density_kg_l or 0.0) * 1000.0
        starts = [next(k for k, t in enumerate(tr.t) if t >= e.at_s) for e in sc.events]
        ends = [*starts[1:], len(tr.t)]
        missing: set[str] = set()
        offending: list[str] = []
        worst: tuple[float, str] | None = None
        for header in self.design.nodes_of("header"):
            a = header.get("wave_speed_m_s")
            design_kpa = header.get("design_kpa")
            dn = header.get("dn_mm")
            named = (("wave_speed_m_s", a), ("design_kpa", design_kpa), ("dn_mm", dn))
            gaps = [k for k, v in named if v is None]
            if gaps:
                missing.update(f"{header.id}.{g}" for g in gaps)
                continue
            assert a is not None and design_kpa is not None and dn is not None
            area = math.pi * (float(dn) / 1000.0) ** 2 / 4.0
            e = self.net.element(header.id)
            i = tr.elements.index(header.id)
            for ev, k0, k1 in zip(sc.events, starts, ends, strict=True):
                before = tr.flow[max(k0 - 1, 0)][i]
                dq = max(abs(tr.flow[k][i] - before) for k in range(k0, k1))
                dv = dq / 60000.0 / area
                surge = rho * float(a) * dv / 1000.0
                window = [tr.pressure[k][j] for k in range(max(k0 - 1, 0), k1) for j in (e.a, e.b)]
                if any(math.isnan(p) for p in window):
                    missing.add(f"expansion tank (CDU fill_kpa) on the loop of {header.id}")
                    continue
                high = max(window) + surge
                low = min(window) - surge
                floor = vapour_kpa(80.0) - P_ATM_KPA  # gauge; 80 °C is above anything here
                head = float(design_kpa) - high
                if worst is None or head < worst[0]:
                    worst = (
                        head,
                        f"{header.id} {high:.0f} kPa(g) peak (surge {surge:.0f} kPa) vs "
                        f"{float(design_kpa):.0f} kPa at {ev.label}",
                    )
                if high > float(design_kpa) or low < floor:
                    side = "above design" if high > float(design_kpa) else "below vapour"
                    offending.append(
                        f"{header.id} {side}: {low:.0f}..{high:.0f} kPa(g) with a "
                        f"{surge:.0f} kPa bound (dv {dv:.2f} m/s) at {ev.label}"
                    )
        if missing:
            return unrun("P-03", sc.run, f"surge not screened; {method}", tuple(sorted(missing)))
        if offending:
            return Result(
                "P-03",
                sc.run,
                Status.WARN,
                f"the bound does not clear: a transient (method of characteristics) study is "
                f"needed; {method}",
                offending=tuple(offending),
            )
        assert worst is not None
        return Result("P-03", sc.run, Status.PASS, f"closest: {worst[1]}; {method}")


# ---------------------------------------------------------------------------------- bench ---


@dataclass(frozen=True)
class Run:
    scenario: Scenario
    trace: Trace | None
    results: list[Result]


@dataclass
class Bench:
    design: Design
    controls: Controls
    net: Network = field(init=False)
    th: Thermal = field(init=False)
    problem: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        try:
            self.net = network.build(self.design)
            self.th = thermal.build(self.net)
            gaps = [*self.net.missing, *self.th.missing]
            if gaps:
                self.problem = f"null values the plant needs: {', '.join(gaps)}"
        except NetworkError as exc:
            self.problem = str(exc)

    def _unrun(self, sc: Scenario, why: str) -> Run:
        return Run(sc, None, [unrun(a, sc.run, why) for a in ("P-01", "P-02", "P-03")])

    def run(self, sc: Scenario) -> Run:
        if self.problem:
            return self._unrun(sc, f"no plant to simulate: {self.problem}")
        ctl = self.controls
        plant = Plant(self.design, self.net, self.th, ctl)
        state = plant.start(sc.mode)
        sol: Solution | None = None
        key: tuple[float, ...] | None = None

        def hydraulics() -> Solution:
            nonlocal sol, key
            op = plant.operating(state)
            k = tuple(round(v, 6) for v in [*op.valve.values(), *op.speed.values()])
            if sol is None or k != key:
                sol, key = network.solve(self.net, op, sol), k
            return sol

        # warm-up from the starting mode: hold t=0 inputs until every loop has settled
        history: list[NDArray[np.float64]] = []
        for _ in range(round(ctl.warmup_s / ctl.dt_s)):
            s = hydraulics()
            plant.control(state, s, ctl.dt_s)
            state.temps = thermal.advance(
                self.th, s, state.temps, plant.boundary(state, sc, 0.0), ctl.dt_s
            )
            history.append(state.temps)
        tail = history[-round(60.0 / ctl.dt_s) :]
        drift = float(np.max(np.ptp(np.array(tail), axis=0))) if tail else math.inf
        if drift > ctl.settled_k:
            return self._unrun(
                sc, f"no steady start: still moving {drift:.2f} K a minute after warm-up"
            )
        if not hydraulics().converged:
            return self._unrun(sc, "the network did not converge in the starting mode")

        monitor = Monitor(self.th)
        pending = list(sc.events)
        label = sc.mode
        steps = round(sc.duration_s / ctl.dt_s)
        for k in range(steps + 1):
            t = k * ctl.dt_s
            while pending and pending[0].at_s <= t:
                ev = pending.pop(0)
                plant.apply(state, ev)
                label = ev.label
            if k:
                plant.actuate(state, ctl.dt_s)
            s = hydraulics()
            if not s.converged:
                why = f"the network did not converge at t={t:.0f} s ({label})"
                return self._unrun(sc, why)
            u = plant.boundary(state, sc, t)
            monitor.sample(t, label, state, s, u)
            if k < steps:
                plant.control(state, s, ctl.dt_s)
                state.temps = thermal.advance(self.th, s, state.temps, u, ctl.dt_s)
        tr = monitor.trace
        return Run(sc, tr, Scoreboard(self.design, self.net, self.th).score(sc, tr))
