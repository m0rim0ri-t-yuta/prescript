# Roadmap — Winter PoC

Goal: a public repository where a pull request that changes a data-center liquid-cooling design is
verified automatically, with a red/green report on the PR — the HDL regression loop, applied to the
cooling loop.

## Why cooling

Liquid-cooling retrofits are where the work is: the hall exists, the grid connection exists, and
the question is how many of the new racks fit into the cooling that is already there. That question
is answered today in spreadsheets, one option at a time. A netlist answers it per pull request, for
every operating mode at once.

## Reference design

`examples/gb200-1su/netlist.yaml`: one NVIDIA GB200 NVL72 scalable unit (8 racks, ~1.2 MW IT),
direct liquid cooled, 2N CDU, N+1 pumps per CDU, rear-door exchangers for the residual air load.
Rack count and IT power follow NVIDIA's public reference architecture; every cooling figure is
marked `assumed` with a round number.

## Milestones

| Week | Deliverable                                                                                      | Exit criterion                                      |
| ---- | ------------------------------------------------------------------------------------------------ | --------------------------------------------------- |
| W0   | Repo, agent config, IR, loader, circulation, `loop_closed`/`dual_path`/`completeness`, CI         | `prescript verify` runs on the reference; CI green ✅ |
| W1   | Cooling IR (grammar v0.2), `loading` on a flow and a heat basis, `inlet_temp`                     | C-05/C-06/C-07 run in every mode they name ✅        |
| W2   | `n_minus_1`, `pressure_drop` (1-D, named method), `balance`, `return_temp`; equipment tables (CSV) | coverage ≥ 90%                                      |
| W3   | Loop diagram SVG (`prescript draw` ✅), `prescript diff` between two netlists ✅, `ride_through` ✅, `consistency` ✅ | coverage 100%                    |
| W4   | GitHub Action: verify ✅ + diff ✅ as one PR comment; README with GIF; 2-minute demo video           | demo PR goes red → fix → green                      |

## Demo script (W4)

Every figure below is measured on the reference design, not estimated.

1. PR: refresh the racks 150 kW → 200 kW (GPU upgrade in an existing hall) — one `heat_kw` in
   `blocks.rack_gb200_nvl72.params`.
2. CI comment goes red — `PASS 27 · FAIL 6 · WARN 0 · UNRUN 0`, and `prescript verify` exits 1.
   Six cells fail, not one: both maintenance modes go down symmetrically, the hall is caught on
   the heat basis as well as the flow basis, and the one isolated branch is caught twice — on
   manifold flow and on pump head.

   | cell                 | finding                                                                                                                                  |
   | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
   | `C-05@maint-cdu-A`   | 12 of 26 elements over rating: CDU-B, PMP-B-1, HDR-S-B and HDR-R-B at 2602/2300 L/min (113%); MAN-B-01…08 at 303/300 L/min (101%)         |
   | `C-05@maint-cdu-B`   | the same, mirrored onto side A                                                                                                           |
   | `C-05@valve-shut-01` | MAN-B-01 at 303/300 L/min (101%) — the rack whose A branch is shut takes its whole flow through B                                         |
   | `C-06@maint-cdu-A`   | CDU-B at 1720/1500 kW (115%) — the surviving unit is short of heat capacity, not just flow                                                |
   | `C-06@maint-cdu-B`   | CDU-A at 1720/1500 kW (115%)                                                                                                             |
   | `C-09@valve-shut-01` | RACK-01 via PMP-B-1 at 253/250 kPa (101%) — the same rack's 303 L/min through one manifold costs side B's pump more head than it has      |

3. Second commit: `cdu_loop` to `rating_kw: 1800`, `rating_lpm: 2800`, `dn_mm: 200` and
   `manifold_lpm: 350` (or a third CDU). The wider bore is margin, not the fix: with DN150 kept,
   the pump-head check still passes at 95%.
4. CI comment goes green — `PASS 33 · FAIL 0 · WARN 0 · UNRUN 0`, worst 93% on flow and 96% on
   heat in `maint-cdu-A` and 91% of the pump's head in `valve-shut-01`: sized, not oversized. The
   diff shows exactly what changed and why.

## Dynamic verification (epic #26)

The static checks above stay the gate. Behind them, `prescript sim` runs a UVM-style testbench
— constrained-random sequences, driver, monitor, scoreboard — against a time-domain plant model
(`docs/SIMULATION.md`).

| Phase | Deliverable                                                                                 | Exit criterion                                  |
| ----- | ------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| 1 #27 | One exchanger and one PID valve; heat steps; settling and valve-authority scoreboard        | `prescript sim` PASS/FAIL per run; pytest green |
| 2     | Plant built from the netlist (CDU, pumps, piping); load and facility-water profiles; cavitation | the reference design simulates in every mode |
| 3     | Fault injection from the netlist's modes; switchover time; rack inlet red line              | `pump-fail-A` and `maint-cdu-A` judged in time  |
| 4     | Thousands of scenarios in CI; functional-coverage report                                    | coverage report on every PR                      |

## Out of scope

CFD, two-phase and immersion cooling, water chemistry and corrosion, the facility water plant
(it enters as a mode condition), leak-detection logic, structural and routing constraints,
pressure-wave transients (water hammer) until a method for them exists, the chiller plant and PUE,
simulator integration beyond CSV export, DXF/PDF ingestion, a web UI, a custom grammar.
