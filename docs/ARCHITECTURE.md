# Architecture

> Prescript: spec-as-code and verification for physical power systems.
> Last updated: 2026-11-11 · grammar v0.1 · PoC

## 1. Why this shape

Chip design stopped "finding out at bring-up" decades ago: a design is text (HDL), a compiler
elaborates it into a netlist, and assertions run against every change in CI. Power-system design for
data centers still moves as drawings, spreadsheets and late simulation studies, and the cross-checks
between them are manual. Prescript borrows the HDL pipeline, not the HDL syntax.

| HDL concept               | Prescript                                                      |
| ------------------------- | --------------------------------------------------------- |
| Module / IP block         | `blocks:` (e.g. `rack_gb200_nvl72`, `ups_block`)          |
| Elaboration               | `loader` expands blocks, synthesizes ATS legs             |
| Netlist                   | `ir.Design` (nodes, edges with breakers/switches)         |
| Test vectors / scenarios  | `modes:` (normal, maint-A, generator, …)                  |
| SVA assertions            | `assertions:` routed to `checks/*`                        |
| Functional coverage       | `coverage` over assertion × mode cells                    |
| Regression in CI          | `prescript verify` on every PR, Markdown report as PR comment  |

## 2. Pipeline

```
netlist.yaml ──▶ loader ──▶ ir.Design ──▶ modes.resolve(mode) ──▶ checks.* ──▶ report
   (text)       parse +       frozen        per-mode states +       pure         text / md / json
               elaborate +   pydantic       energized node set    functions
               validate                            │                    ▲
                                                   └──▶ flow.compute ───┘
                                                        per-mode kW on nodes/edges
```

Each stage consumes only the previous stage's output. Checks never read YAML; the report never
re-runs checks.

## 3. Modules

| Module                | Responsibility                                                          |
| --------------------- | ----------------------------------------------------------------------- |
| `prescript/ir.py`          | Frozen IR types. Units in field names. `None` = undecided rating.       |
| `prescript/loader.py`      | YAML 1.2-bool parsing, block elaboration, ATS legs, validation          |
| `prescript/modes.py`       | Resolve overrides → node/device states; BFS energization from live sources |
| `prescript/flow.py`        | Lossless radial flow: demand × class factor pushed up live feeds         |
| `prescript/result.py`      | Closed status set and the invariants a `Result` enforces at construction |
| `prescript/checks/`        | One routine per module; `REGISTRY` + `PLANNED`                          |
| `prescript/engine.py`      | Assertion × mode loop, severity, coverage                               |
| `prescript/report.py`      | Matrix + findings as text, Markdown, JSON                               |
| `prescript/cli.py`         | `prescript verify`, `prescript elaborate`                                         |

## 4. Design decisions

1. **`null` never passes.** The verifier's value is that a green result means something. Missing
   ratings and unimplemented routines are `UNRUN`; `Result` refuses a `PASS` that carries missing
   data and a `FAIL` without evidence. (`agent-config/rules/verification-semantics.md`)
2. **Topology first, physics later.** v0.1 answers "is it connected and energized in this mode?".
   Loading (W1) adds a lossless radial flow on top of the same energization; short-circuit duty and dynamics come last and only with a named,
   defensible method. Industry simulators are export targets, not something Prescript re-implements.
3. **Modes are data.** A scenario is an override map plus demand factors, so adding a failure case is
   a YAML change reviewed like code.
4. **YAML now, grammar later.** Following Verilog's path: get the semantics right in a plain
   format before investing in a dedicated syntax. The IR is the stable contract; a future grammar
   compiles to it.
5. **Provenance is part of the data.** Every rated element says where its numbers came from, so a
   reviewer can tell a datasheet value from an assumption.

## 5. Energization model (v0.1)

- Live sources: `source` not `off`; `generator` `on`; `ups` in `battery`.
- A node in state `off` is dead and blocks propagation.
- An edge conducts when its device (if any) is `closed`; an ATS leg conducts only for the selected
  source; a UPS in `bypass` accepts power only through its `bypass_input` edge.
- `bidirectional: true` edges (bus ties) conduct both ways when closed.

## 6. Out of scope for the PoC

Short-circuit studies beyond a simplified screen, harmonics, arc flash, protection coordination,
reading DXF/PDF drawings, a web UI, a custom grammar. See `ROADMAP.md`.
