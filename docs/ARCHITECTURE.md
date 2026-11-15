# Architecture

> Prescript: spec-as-code and verification for data-center liquid cooling.
> Last updated: 2026-11-13 · grammar v0.2 · PoC

## 1. Why this shape

Chip design stopped "finding out at bring-up" decades ago: a design is text (HDL), a compiler
elaborates it into a netlist, and assertions run against every change in CI. Cooling design for
data centers still moves as drawings, spreadsheets and late CFD studies, and the cross-checks
between them are manual — on a retrofit, inside a hall that is already running. Prescript borrows
the HDL pipeline, not the HDL syntax.

| HDL concept               | Prescript                                                   |
| ------------------------- | ----------------------------------------------------------- |
| Module / IP block         | `blocks:` (e.g. `rack_gb200_nvl72`, `cdu_loop`)             |
| Elaboration               | `loader` expands blocks                                     |
| Netlist                   | `ir.Design` (nodes, edges with valves)                      |
| Test vectors / scenarios  | `modes:` (normal, maint-cdu-A, summer-peak, …)              |
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

## 3. Modules

| Module                 | Responsibility                                                          |
| ---------------------- | ----------------------------------------------------------------------- |
| `prescript/ir.py`      | Frozen IR types. Units in field names. `None` = undecided rating.       |
| `prescript/loader.py`  | YAML 1.2-bool parsing, fluids, block elaboration, validation            |
| `prescript/modes.py`   | Resolve overrides → equipment/valve states; circulation and dead legs   |
| `prescript/result.py`  | Closed status set and the invariants a `Result` enforces at construction |
| `prescript/checks/`    | One routine per module; `REGISTRY` + `PLANNED`; `_util.accumulate`      |
| `prescript/engine.py`  | Assertion × mode loop, severity, coverage                               |
| `prescript/report.py`  | Matrix + findings as text, Markdown, JSON                               |
| `prescript/sim/`       | Plant model, PID, UVM-style testbench and its report (`SIMULATION.md`)   |
| `prescript/cli.py`     | `prescript verify`, `prescript elaborate`, `prescript sim`              |

## 4. Design decisions

1. **`null` never passes.** The verifier's value is that a green result means something. Missing
   ratings and unimplemented routines are `UNRUN`; `Result` refuses a `PASS` that carries missing
   data and a `FAIL` without evidence. (`agent-config/rules/verification-semantics.md`)
2. **A loop, not a tree.** Power flows from a source to a load; coolant has to come back. Edges
   point the way the fluid travels, so a design is a set of cycles, and a supply path whose return
   leg is isolated fails `loop_closed` rather than quietly passing.
3. **Topology first, physics later.** v0.2 answers "does it circulate, and does every element stay
   inside its rating?" using the steady-state sensible-heat balance `Q = V · rho · cp · dT`.
   Pressure drop and flow balance between racks come with a named, defensible method. Transient
   behaviour is a separate stage, `prescript sim` (`SIMULATION.md`): a lumped plant model driven
   by a UVM-style testbench, after the static checks and never instead of them. Industry
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
