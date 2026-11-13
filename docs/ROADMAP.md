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
| W3   | Loop diagram SVG (`prescript draw`), `prescript diff` between two netlists, `ride_through`, `consistency` | coverage 100%                              |
| W4   | GitHub Action: verify + diff as a PR comment; README with GIF; 2-minute demo video                | demo PR goes red → fix → green                      |

## Demo script (W4)

1. PR: refresh the racks 150 kW → 200 kW (GPU upgrade in an existing hall).
2. CI comment goes red: in `maint-cdu-A` the surviving CDU carries 2602 of 2300 L/min and all eight
   B-side manifolds sit at 101% of their rating.
3. Second commit: larger CDU and manifolds, or a third CDU.
4. CI comment goes green; the diff shows exactly what changed and why.

## Out of scope

CFD, two-phase and immersion cooling, water chemistry and corrosion, the facility water plant
(it enters as a mode condition), leak-detection logic, structural and routing constraints,
simulator integration beyond CSV export, DXF/PDF ingestion, a web UI, a custom grammar.
