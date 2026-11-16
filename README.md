# Prescript

**Chip-design discipline for data-center liquid cooling.**

Chip designers stopped "finding out at bring-up" decades ago: designs are text, a compiler
elaborates them, and assertions run on every change. Liquid-cooling retrofits still move as
drawings and spreadsheets, checked by hand — while the hall they are being fitted into is already
running. Prescript applies the HDL regression loop to the cooling loop: write the design as a
netlist, declare what must hold in every operating mode, and let CI tell you on each pull request.

> Status: winter PoC, grammar v0.3. Not for engineering use. See [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Try it

```bash
uv sync
uv run prescript verify examples/gb200-1su/netlist.yaml
```

```
id    check          normal  maint-cdu-A  maint-cdu-B  pump-fail-A  summer-peak  valve-shut-01  facility-loss  stop-cdu-A@s1  stop-cdu-A@s2  stop-cdu-A@s3  stop-cdu-A@s4  static  meta
----  -------------  ------  -----------  -----------  -----------  -----------  -------------  -------------  -------------  -------------  -------------  -------------  ------  ----
C-01  loop_closed    PASS                              PASS         PASS         PASS                          PASS           PASS           PASS           PASS
C-02  dual_path      PASS                              PASS         PASS
C-03  loop_closed            PASS         PASS
C-05  loading        PASS    PASS         PASS         PASS         PASS         PASS                          PASS           PASS           PASS           PASS
C-07  inlet_temp     PASS                                           PASS
C-08  n_minus_1      PASS
C-09  pressure_drop  PASS                                                        PASS
C-10  balance        PASS                                                        PASS
...
PASS 45 · FAIL 0 · WARN 0 · UNRUN 0
assumed  stop-cdu-A@s1  standby start inhibited at the controller (provenance: assumed)
assumed  stop-cdu-A@s2  loss of pump running feedback (provenance: assumed)
```

`UNRUN` is deliberate: a check that touches an undecided (`null`) rating, or that is not built yet,
never reports `PASS`. The reference design has none left — every routine it names is built — and an
assertion is not asked for in a mode where it could never mean anything.

The same netlist as a picture — one operating mode's states on the loop:

```bash
uv run prescript draw examples/gb200-1su/netlist.yaml --mode maint-cdu-A -o loop.svg
```

`draw` renders; it does not verify. A rating the netlist leaves undecided is drawn as `?`.

An operating procedure is written step by step under `procedures:`, and every step becomes a mode
the assertions run in — the `stop-cdu-A@s1 … @s4` columns above. Its `done_when` conditions are
plant feedback nobody computes, so the report lists them as `assumed`. The same procedure as a
storyboard, one diagram per step:

```bash
uv run prescript draw examples/gb200-1su/netlist.yaml --procedure stop-cdu-A -o frames/
```

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
| ASM chart                | `procedures:` — each step elaborates into a mode    |
| SVA assertions           | `assertions:` — closed loop, dual path, loading, …  |
| Functional coverage      | assertion × mode coverage                           |
| Regression in CI         | `prescript verify` comment on every PR              |
| Revision diff            | `prescript diff` — what an edit really changed      |
| Schematic view           | `prescript draw` — the netlist as a loop diagram    |
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
