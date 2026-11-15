# Dynamic verification (`prescript sim`)

> Epic #26, Phase 1 #27. The static checks (`prescript verify`) answer "does it circulate, and does
> every element stay inside its rating in every mode?". This answers "does the loop, with its
> controller, ride through what happens to it over time?" — the UVM regression loop, applied to a
> plant model.

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

## Next phases (#26)

- Phase 2: build the plant from a netlist (CDU, pumps, piping); facility-water and IT-load profiles
  instead of a single step; cavitation (pump suction above vapour pressure).
- Phase 3: fault injection — the netlist's modes (`pump-fail-A`, `maint-cdu-A`, …) as scenarios;
  switchover time and the rack inlet red line.
- Phase 4: thousands of scenarios in CI with a functional-coverage report.
