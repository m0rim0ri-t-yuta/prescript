# Roadmap — Winter PoC

Goal: a public repository where a pull request that changes a data-center power design is verified
automatically, with a red/green report on the PR — the HDL regression loop, applied to power.

## Reference design

`examples/gb200-1su/netlist.yaml`: one NVIDIA GB200 NVL72 scalable unit (8 racks, ~1.2 MW IT),
Tier III, 2N electrical, generator + ATS for essential loads. Rack-level figures follow NVIDIA's
public reference architecture; everything else is marked `assumed` with round numbers.

## Milestones

| Week | Deliverable                                                                        | Exit criterion                                        |
| ---- | ---------------------------------------------------------------------------------- | ----------------------------------------------------- |
| W0   | Repo, agent config, IR, loader, energization, `dual_path`/`path_exists`/`completeness`, CI | `keel verify` runs on the reference; CI green  ✅   |
| W1   | `loading` (kVA/A basis) with demand factors; equipment and power-path tables (CSV)  | A-06/A-07/A-09 run in every mode                      |
| W2   | `n_minus_1`, `diverse_upstream`, `standby_diverse`, `generator_margin`, `time_margin` | coverage ≥ 90%                                       |
| W3   | Single-line diagram SVG (`keel draw`), `keel diff` between two netlists, `consistency`, simplified `breaker_duty` | coverage 100%    |
| W4   | GitHub Action: verify + diff as a PR comment; README with GIF; 2-minute demo video   | demo PR goes red → fix → green                         |

## Demo script (W4)

1. PR: retrofit racks 150 kW → 200 kW (GPU refresh in an existing hall).
2. CI comment goes red: UPS-B overloaded in `maint-A`, rack PDUs above continuous rating.
3. Second commit: larger UPS block and PDU rating.
4. CI comment goes green; diff shows exactly what changed and why.

## Out of scope

Accurate short-circuit / arc flash / protection coordination, simulator integration beyond CSV
export, DXF/PDF ingestion, a web UI, a custom grammar, networking.
