# Architecture

> Prescript: spec-as-code and verification for data-center liquid cooling.
> Last updated: 2026-11-15 · grammar v0.3 · PoC

## 1. Why this shape

Chip design stopped "finding out at bring-up" decades ago: a design is text (HDL), a compiler
elaborates it into a netlist, and assertions run against every change in CI. Cooling design for
data centers still moves as drawings, spreadsheets and late CFD studies, and the cross-checks
between them are manual — on a retrofit, inside a hall that is already running. Prescript borrows
the HDL pipeline, not the HDL syntax.

| HDL concept               | Prescript                                                   |
| ------------------------- | ----------------------------------------------------------- |
| Module / IP block         | `blocks:` (e.g. `rack_gb200_nvl72`, `cdu_loop`)             |
| Elaboration               | `loader` expands blocks and procedures                      |
| Netlist                   | `ir.Design` (nodes, edges with valves)                      |
| Test vectors / scenarios  | `modes:` (normal, maint-cdu-A, summer-peak, …)              |
| ASM chart (procedure)     | `procedures:`, each step elaborated into a mode             |
| SVA assertions            | `assertions:` routed to `checks/*`                          |
| Functional coverage       | `coverage` over assertion × mode cells                      |
| Regression in CI          | `prescript verify` on every PR, Markdown report as a comment |

## 2. Pipeline

```
netlist.yaml ──▶ loader ──▶ ir.Design ──▶ modes.resolve(mode) ──▶ checks.* ──▶ report
   (text)       parse +       frozen        per-mode states +       pure         text / md / json
               elaborate +   pydantic       circulating/draining   functions
               validate
```

Each stage consumes only the previous stage's output. Checks never read YAML; the report never
re-runs checks.

`checks` is not the only consumer of the IR. `draw` reads one design:

```
ir.Design (+ modes.resolve(mode)) ──▶ draw.to_svg ──▶ loop diagram (SVG)
```

It renders what the netlist says — topology, the states of one mode, the ratings as written — and
reports no pass or fail. An undecided rating is drawn as `?`, never as a number.

`diff` reads two: two elaborated designs in, the list of differences out. It compares after
elaboration, which is why one edited block parameter reads as the eight racks it moved, and it
reports facts — whether a change breaks an assertion is `verify`'s answer.

## 3. Modules

| Module                 | Responsibility                                                          |
| ---------------------- | ----------------------------------------------------------------------- |
| `prescript/ir.py`      | Frozen IR types: nodes, edges, modes, procedures, spec tables. `None` = undecided. |
| `prescript/loader.py`  | YAML 1.2-bool parsing, fluids, block and procedure elaboration, validation |
| `prescript/modes.py`   | Resolve overrides → equipment/valve states; circulation and dead legs   |
| `prescript/result.py`  | Closed status set and the invariants a `Result` enforces at construction |
| `prescript/checks/`    | One routine per module; `REGISTRY` + `PLANNED`; `_util.accumulate`      |
| `prescript/core/`     | Domain-neutral core (§3.1): `spec` protocols, `engine.run`, `report`    |
| `prescript/engine.py`  | Cooling on the core: `REGISTRY`, `modes.resolve` as the mode state, coverage |
| `prescript/report.py`  | Cooling on the core: adds the `done_when` assumptions to the core's output |
| `prescript/diff.py`    | Two elaborated designs → a change list; text, Markdown, JSON            |
| `prescript/draw.py`    | IR → loop diagram (SVG): columns from the CDU, return lanes; procedure storyboard |
| `prescript/sim/`       | Plant models (Phase 1 hand-written, Phase 2 from the netlist), PID, UVM-style testbench, report (`SIMULATION.md`) |
| `prescript/cli.py`     | `verify`, `elaborate`, `diff`, `draw`, `sim`                            |

### 3.1 The core and its domains

`prescript.core` is what a domain library imports instead of copying. It reads a domain's design
only through `core.spec`: `project`, `modes` by name, and `assertions` with `id`, `check`,
`modes` and `severity`. The domain supplies its routines by name, a function that builds one
mode's state, and optional post-checks such as `coverage`:

```python
core.engine.run(design, registry, state, planned=..., post=...)  # -> list[Result]
```

The rules that make a result trustworthy are the core's, so every domain gets them: an unbuilt or
unknown check is `UNRUN`; a mode whose `state` raises `core.engine.Unsolvable` is `UNRUN` in every
assertion with that reason while the other modes still run; `static` and `meta` get no state; a
`warn` assertion turns `FAIL` into `WARN`. `core.report` renders the matrix, summary and findings
with the domain's title and extra lines, and `core.report.exit_code` is `verify`'s exit status.
`prescript.result` belongs to the core too and stays at the top level, where domains import it.

The cooling domain sits on the core like any other: `engine.py` and `report.py` are its adapters.

## 4. Design decisions

1. **`null` never passes.** The verifier's value is that a green result means something. Missing
   ratings and unimplemented routines are `UNRUN`; `Result` refuses a `PASS` that carries missing
   data and a `FAIL` without evidence. (`agent-config/rules/verification-semantics.md`)
2. **A loop, not a tree.** Power flows from a source to a load; coolant has to come back. Edges
   point the way the fluid travels, so a design is a set of cycles, and a supply path whose return
   leg is isolated fails `loop_closed` rather than quietly passing.
3. **Topology first, physics later.** v0.2 answers "does it circulate, does every element stay
   inside its rating, does every rack get its share, and can the pump push it?" with the
   steady-state sensible-heat balance `Q = V · rho · cp · dT`, a rating-limited flow balance and a
   1-D pressure-drop screening — each method named in its results. Solving the network and the
   pump curve stay out of the static checks. Transient behaviour is a separate stage,
   `prescript sim` (`SIMULATION.md`): the netlist's own network and a lumped heat model, driven by a
   UVM-style testbench — a procedure's steps on a time axis — after the static checks and never
   instead of them. Industry
   simulators are export targets, not something Prescript re-implements.
4. **The facility loop is a boundary condition.** The scope is the technology cooling loop (TCS)
   on the rack side of the CDU, because that is what a retrofit changes. What the facility water
   loop (FWS) delivers enters as a mode `condition`, not as modelled plant.
5. **Modes are data.** A scenario is an override map, demand factors and conditions, so adding a
   failure case is a YAML change reviewed like code.
6. **YAML now, grammar later.** Following Verilog's path: get the semantics right in a plain
   format before investing in a dedicated syntax. The IR is the stable contract.
7. **Provenance is part of the data.** Every element says where its numbers came from, so a
   reviewer can tell a datasheet value from an assumption.

## 5. Circulation model (v0.2)

- Flow sources: a `cdu` whose state is `on`. A node in state `off` or `standby` is dead and blocks
  propagation, so an N+1 standby pump carries nothing until a mode starts it.
- An edge conducts when its valve (if any) is `open`. A valve defaults to `open` — the opposite of
  a breaker, and the usual source of a sign error when porting power rules.
- `circulating` is what a running CDU can reach; `draining` is what can reach a running CDU back.
  A branch that is in the first set and not in the second is a **dead leg**: fluid could enter it,
  but there is no circuit, so it carries no flow.
- Flow and heat are accumulated per load around its own loop (`checks/_util.accumulate`): up the
  supply side to the CDU, then down the return side back to it, splitting by the edge `share` at
  every branch. The CDU is where the loop is cut, so nothing is charged twice.

## 6. Out of scope for the PoC

CFD, two-phase and immersion cooling, pressure-drop and pump-curve solving beyond a screening
estimate, water chemistry, the facility water plant, leak-detection logic, reading DXF/PDF
drawings, a web UI, a custom grammar. See `ROADMAP.md`.
