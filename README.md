# Keel

**Chip-design discipline for physical power systems.**

Chip designers stopped "finding out at bring-up" decades ago: designs are text, a compiler
elaborates them, and assertions run on every change. Data-center power design still moves as
drawings and spreadsheets, checked by hand. Keel applies the HDL regression loop to power: write the
design as a netlist, declare what must hold in every operating mode, and let CI tell you on each pull
request.

> Status: winter PoC, grammar v0.1. Not for engineering use. See [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Try it

```bash
uv sync
uv run keel verify examples/gb200-1su/netlist.yaml
```

```
id    check             normal  maint-A  maint-B  ups-bypass-A  generator  dead-pod  tie-closed  static  meta
A-01  dual_path         PASS                      PASS          PASS       PASS      PASS
A-16  path_exists               PASS     PASS
A-06  loading           UNRUN   UNRUN    UNRUN    UNRUN         UNRUN      UNRUN     UNRUN
A-14  completeness                                                                               WARN
...
PASS 8 · FAIL 0 · WARN 2 · UNRUN 24
```

`UNRUN` is deliberate: a check that touches an undecided (`null`) rating, or that is not built yet,
never reports `PASS`.

## How it maps to HDL

| HDL                      | Keel                                             |
| ------------------------ | ------------------------------------------------ |
| Module / IP              | `blocks:` — e.g. a GB200 NVL72 rack, a UPS block |
| Elaboration → netlist    | `keel elaborate`                                 |
| Test scenarios           | `modes:` — normal, maint-A, generator, …         |
| SVA assertions           | `assertions:` — dual path, N-1, loading, …       |
| Functional coverage      | assertion × mode coverage                        |
| Regression in CI         | `keel verify` comment on every PR                |

## Reference design

One NVIDIA GB200 NVL72 scalable unit (8 racks, ~1.2 MW IT), Tier III, 2N. Rack figures follow
NVIDIA's public reference architecture; everything else is marked `assumed`. Only public data is
accepted in this repository.

## Docs

[Architecture](docs/ARCHITECTURE.md) · [Netlist language](docs/KEEL-LANGUAGE.md) ·
[Checks](docs/CHECKS.md) · [Development](docs/DEVELOPMENT.md) · [Roadmap](docs/ROADMAP.md)

Contributors and coding agents: start at [`AGENTS.md`](AGENTS.md).

## License

Apache-2.0
