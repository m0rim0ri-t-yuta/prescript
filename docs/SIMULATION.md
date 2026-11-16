# Dynamic verification (`prescript sim`)

> Epic #26, Phase 1 #27, Phase 2 #45. The static checks (`prescript verify`) answer "does it
> circulate, and does every element stay inside its rating in every mode?". This answers "does the
> loop, with its controller, ride through what happens to it over time?" — the UVM regression
> loop, applied to a plant model.

## How it maps to UVM

| UVM                  | Prescript (`src/prescript/sim/`)                                           |
| -------------------- | -------------------------------------------------------------------------- |
| DUT                  | `plant.py` — the plant model, integrated with `scipy.integrate.solve_ivp`   |
| Sequence item        | `uvm.LoadStep` — one scenario: a heat step at a facility-water temperature |
| Sequence (+ seed)    | `uvm.StepSequence` — constrained random; the same seed gives the same runs |
| Driver               | `uvm.Driver` — the item as boundary conditions on the time axis            |
| Monitor              | `uvm.Monitor` — samples plant and controller every controller period       |
| Scoreboard           | `uvm.Scoreboard` — judges the trace; returns `Result`s (PASS/FAIL/WARN/UNRUN) |
| Environment / test   | `uvm.Bench` — wires the parts, closes the loop, runs one item              |
| Regression           | `prescript sim --seed N --runs K`; `hypothesis` in `tests/test_sim.py`     |

pyuvm is not used: it schedules through cocotb, whose examples run on an HDL simulator
(https://pypi.org/project/pyuvm/ — 5.0.0 depends on `cocotb<3.0,>=1.6.0`). A plant model has no HDL
simulator to run on, and whether pyuvm can run without one is unverified. The UVM roles are kept;
the implementation is plain Python.

## Phase 1 plant

One CDU liquid-to-liquid exchanger with a PID control valve on the facility-water side
(`src/prescript/sim/poc.py`). Every value is `assumed`.

| Quantity                          | Value                       |
| --------------------------------- | --------------------------- |
| Secondary (TCS) flow, constant    | 300 L/min PG25 (3.85 × 1.03 kJ/(L·K), as the reference design) |
| Facility water, valve fully open  | 200 L/min, 4.18 kJ/(L·K)    |
| Exchanger UA                      | 30 kW/K                     |
| Coolant in the hot / cold node    | 100 L / 100 L               |
| Valve actuator time constant      | 5 s, linear characteristic  |
| Controller                        | PI (kp 0.1 per K, Ti 20 s), 1 s sample, setpoint 40 °C |

**Method** (named in every result's `detail`): two-node lumped capacitance on the secondary side
— a hot node (racks and return) and a cold node (exchanger outlet and supply) — a counterflow
ε-NTU exchanger, a first-order valve actuator, integrated with `solve_ivp` (RK45) between
controller samples with the inputs held (zero-order hold).

Not modelled: pump dynamics, transport delay, pressure, the facility water plant (its supply
temperature is a boundary condition), heat loss to the room. Pressure-wave transients (water
hammer) need a method such as the method of characteristics and are out of reach of a lumped
model; they stay `UNRUN` until one exists.

The exchanger's steady-state capacity at full stroke while holding 40 °C, from
`plant.capacity_kw`: 354.5 kW with 24 °C water, 265.9 kW at 28 °C, 177.3 kW at 32 °C.

## Scenarios

`poc.ENVELOPE`: the heat steps between two values drawn from 30–150 kW at a whole second drawn
from 60–180 s; the facility water is drawn from 24–32 °C. Each run starts in steady state at the
first heat value, with the controller bumpless. The run lasts 900 s.

## Scoreboard

| id   | What it holds                                                                       | FAIL evidence                       |
| ---- | ----------------------------------------------------------------------------------- | ----------------------------------- |
| S-01 | `TT-HX01` (supply) back within 40.0 ± 0.5 °C no later than 300 s after the step, and still there at the end | the worst sample past the limit |
| S-02 | `CV-01` command off both stroke ends once settled (the loop still has authority), and the valve position inside 0–100% throughout | the sample at the stroke end and how many there were |

Both are `UNRUN` when the run cannot show them: when it ends less than 120 s after the 300 s limit,
or when no valve position can hold 40 °C at the starting load (no steady state to start from).

## Running it

```bash
uv run prescript sim                        # seed 1, 20 runs inside the envelope: exit 0
uv run prescript sim --seed 7 --runs 200    # another seed, more runs
uv run prescript sim --max-heat-kw 260      # widen the envelope past the capacity: exit 1
```

Exit codes: 1 on any `FAIL`, 2 on a bad option, 0 otherwise.

## Phase 2 — the plant is the netlist (#45)

`prescript sim <netlist.yaml>` builds the device under test from the netlist itself: every CDU,
pump, header, manifold, rack, rear door and valve in it. Nothing about the plant is written in
the testbench. Without a netlist, `prescript sim` is Phase 1, unchanged.

```bash
uv run prescript sim examples/gb200-1su/netlist.yaml                      # from `normal`, run-00 + 5 random
uv run prescript sim examples/gb200-1su/netlist.yaml -m summer-peak       # from another mode
uv run prescript sim examples/gb200-1su/netlist.yaml -p stop-cdu-A \
    --plot sim.svg --trace sim.csv                                        # a procedure on a time axis
./scripts/demo-procedure.sh                                               # procedure -> diagrams -> simulation
```

### Procedures drive the simulation

A procedure (`procedures:`, `docs/PRESCRIPT-LANGUAGE.md`) is the ASM chart of an operation. The
static checks evaluate each step as a mode (`stop-cdu-A@s1` …). `sim -p` applies the same steps,
in order, to the running plant: step *k*'s `set:` lands `after_s` seconds after step *k-1*
(`netbench.events_from`). A step without `after_s` stops the simulation with an error — the
simulator does not invent a time. The report's timeline shows the loop at the end of every state,
and every finding names the step it happened in.

| UVM                  | Phase 2 (`src/prescript/sim/`)                                              |
| -------------------- | --------------------------------------------------------------------------- |
| DUT                  | `network.py` + `thermal.py`, built from the netlist                         |
| Sequence item        | `netbench.Scenario` — start mode, events, IT-load and facility-water profiles |
| Sequence (+ seed)    | `netbench.ScenarioSequence` — run-00 as written, then constrained random     |
| Driver               | `netbench.Plant` — events, valve strokes, pump ramps, one PI loop per CDU    |
| Monitor              | `netbench.Monitor` → `Trace` (every node, element and junction, every second) |
| Scoreboard           | `netbench.Scoreboard` — P-01, P-02, P-03                                     |

### Method

Named in every result's `detail`.

- **Hydraulics** (`network.py`): every node is an element between an inlet and an outlet junction;
  an edge joins them, through its valve when it has one. Headers use Darcy-Weisbach with
  Swamee-Jain and equipment its rated drop scaled with `Q^2` — the same functions as C-09
  (`pressure_drop`). Valves are `Kv` with a linear stroke. Pumps follow a quadratic curve through
  `shutoff_kpa` and the rated point, scaled with speed by the affinity laws; a stopped pump has a
  check valve and carries nothing either way. Solved quasi-steadily (Newton on junction pressures
  and element flows) whenever an actuator moves: fluid inertia is neglected, so the flows follow
  the valves and pumps instantly.
- **Pressure reference**: a closed loop has one point of no pressure change. The first CDU (netlist
  order) with `fill_kpa` in a connected loop is its expansion tank. A loop without one still
  circulates, but has no absolute pressure, and P-01/P-03 are `UNRUN` there.
- **Heat** (`thermal.py`): one well-mixed volume per node (`volume_l`, a header's from its bore and
  run), flow-weighted mixing at junctions, the load's `heat_kw` × the mode's demand × the IT
  profile into each load. Each CDU is a counterflow ε-NTU exchanger whose UA is sized from its own
  rated point (`rating_kw` at `approach_k`, `rating_lpm` secondary, `facility_lpm` primary). Linear
  between samples, so it is integrated exactly with a matrix exponential.
- **Control**: one PI loop per running CDU (kp 0.05 per K, Ti 60 s, 5 s valve actuator, 1 s
  sample — `mvp.CONTROLS`, all `assumed`) on its facility-water valve, holding the CDU's secondary
  supply at its `supply_c`.
- **Start**: each run holds the start mode's inputs for 1200 s, unrecorded, and only starts if no
  node is still moving more than 0.05 K a minute. A mode with no running CDU (`facility-loss`)
  never settles and every check reports `UNRUN` — a trip from a running state is Phase 3.

Not modelled: fluid inertia and pressure waves, transport delay along a pipe, elevation, heat loss
to the room, the facility water plant (its temperature is a boundary condition), automatic
standby start (Phase 3).

### Scenarios

run-00 is the scenario as written: the procedure's own times, IT at 100 % of the mode's demand,
facility water at the mode's `facility_supply_c`. Then `--runs K` random runs from `--seed`
(`mvp.ENVELOPE`): every gap between steps stretched 0.5–1.5×, the IT load moving between 60 % and
100 % every 2–5 minutes, the facility water up to 2 K either side and drifting across the run. Each
run lasts until 600 s after the last step.

### Scoreboard

| id   | What it holds                                                                 | FAIL evidence |
| ---- | ----------------------------------------------------------------------------- | ------------- |
| P-01 | Cavitation: at every running pump, NPSH available (suction pressure from the network, water vapour pressure by Antoine — conservative for PG25) ≥ NPSH required (`npshr_m` at the rated flow, scaled with `(Q/Qr)^2` above it) | the first sample below, per pump, with its step |
| P-02 | The coolant a load sees — its inlet, or what it holds when nothing flows through it — never above its `max_inlet_c` | the first sample above, per load, with its step |
| P-03 | Surge screen, never a FAIL: for every event, each header's velocity change taken as instantaneous gives the Joukowsky bound `rho * a * dv`. If the quasi-steady pressure ± the bound stays inside `design_kpa` and above vapour pressure, PASS; otherwise WARN — a method-of-characteristics study is needed. `UNRUN` with no event. Pipes without a bore in the netlist (branch runs) are not screened | — (WARN lists each header and event) |

A `null` a check needs (`npshr_m`, `max_inlet_c`, `wave_speed_m_s`, …) makes that check `UNRUN`
and names the field; a `null` the plant needs (`shutoff_kpa`, `volume_l`, `facility_lpm`, …) makes
every check `UNRUN`.

### What the reference design shows

`prescript sim examples/gb200-1su/netlist.yaml -p stop-cdu-A`: CDU-B goes from 1575 to 2308 L/min
when the duty pump of CDU-A stops (s2), its supply peaks at 31.4 °C and settles back to 30 °C;
P-01 and P-02 pass. P-03 is a WARN at s2: stopping a pump that carries 1575 L/min is a 1.48 m/s
change in its header, and the instantaneous bound (about 1.8 MPa) does not clear 1000 kPa. That is
what the screen is for: the model cannot say the stop is safe, so it says a transient study is
needed rather than PASS.

With the expansion tank's fill pressure at 10 kPa instead of 100 (`scripts/demo-procedure.sh`,
step 4), every static check still passes, and P-01 fails at s2: PMP-B-1 carrying the whole hall
has 2.3 m of NPSH against 3.0 m required.

## Next phases (#26)

- Phase 3: fault injection — trips and sensor faults as events; automatic standby start and
  switchover time; the rack inlet red line; ride-through from a running state (`facility-loss`).
- Phase 4: thousands of scenarios in CI with a functional-coverage report.
