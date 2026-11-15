# Prescript

**Chip-design discipline for data-center liquid cooling.**

Chip designers stopped "finding out at bring-up" decades ago: designs are text, a compiler
elaborates them, and assertions run on every change. Liquid-cooling retrofits still move as
drawings and spreadsheets, checked by hand — while the hall they are being fitted into is already
running. Prescript applies the HDL regression loop to the cooling loop: write the design as a
netlist, declare what must hold in every operating mode, and let CI tell you on each pull request.

> Status: winter PoC, grammar v0.2. Not for engineering use. See [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Try it

```bash
uv sync
uv run prescript verify examples/gb200-1su/netlist.yaml
```

```
id    check          normal  maint-cdu-A  maint-cdu-B  pump-fail-A  summer-peak  valve-shut-01  facility-loss  static  meta
----  -------------  ------  -----------  -----------  -----------  -----------  -------------  -------------  ------  ----
C-01  loop_closed    PASS                              PASS         PASS         PASS
C-02  dual_path      PASS                              PASS         PASS
C-03  loop_closed            PASS         PASS
C-05  loading        PASS    PASS         PASS         PASS         PASS         PASS
C-07  inlet_temp     PASS                                           PASS
C-08  n_minus_1      PASS
C-09  pressure_drop  PASS                                                        PASS
C-10  balance        PASS                                                        PASS
...
PASS 28 · FAIL 0 · WARN 1 · UNRUN 4
```

`UNRUN` is deliberate: a check that touches an undecided (`null`) rating, or that is not built yet,
never reports `PASS`. Every `UNRUN` above is a routine that is not built yet; an assertion is not
asked for in a mode where it could never mean anything.

## What it checks that a power tool would not

A cooling loop is a loop. A rack that is supplied but whose return leg is isolated still cooks, and
a return header downstream of a stopped CDU is a dead leg that carries nothing. `loop_closed` asks
for a closed circuit, and flow is accumulated around that circuit — up the supply side to the CDU
and back down the return side — so taking one CDU out moves the whole hall onto the other one's
headers, in the numbers.

## How it maps to HDL

| HDL                      | Prescript                                           |
| ------------------------ | --------------------------------------------------- |
| Module / IP              | `blocks:` — e.g. a GB200 NVL72 rack, a CDU loop     |
| Elaboration → netlist    | `prescript elaborate`                               |
| Test scenarios           | `modes:` — normal, maint-cdu-A, summer-peak, …      |
| SVA assertions           | `assertions:` — closed loop, dual path, loading, …  |
| Functional coverage      | assertion × mode coverage                           |
| Regression in CI         | `prescript verify` comment on every PR              |
| UVM testbench            | `prescript sim` — random load steps on a plant model |

## Reference design

One NVIDIA GB200 NVL72 scalable unit (8 racks, ~1.2 MW IT), direct liquid cooled, 2N CDU. Rack
count and IT power follow NVIDIA's public reference architecture; every cooling figure is marked
`assumed` with a round number. Only public data is accepted in this repository.

## Docs

[Architecture](docs/ARCHITECTURE.md) · [Netlist language](docs/PRESCRIPT-LANGUAGE.md) ·
[Checks](docs/CHECKS.md) · [Simulation](docs/SIMULATION.md) · [Development](docs/DEVELOPMENT.md) ·
[Roadmap](docs/ROADMAP.md)

Contributors and coding agents: start at [`AGENTS.md`](AGENTS.md).

## License

Apache-2.0
