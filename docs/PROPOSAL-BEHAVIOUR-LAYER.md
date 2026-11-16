# Proposal — The Behaviour Layer (grammar v0.3)

> **Status: Part B is implemented, as `procedures:` (grammar v0.3, #44). Parts A (`kinds:`) and C
> (transition assertions) are still proposals.** `docs/PRESCRIPT-LANGUAGE.md` is the SSOT for what
> the loader accepts; where it and §4 differ, it wins. Part B shipped without Part A, on the
> existing overrides. Open questions settled by #44: 3 — steps are cumulative deltas and
> `prescript elaborate` prints each step's absolute overrides; 4 — procedures stay in the netlist
> file for now; 6 — the key is `procedures:`. The reference design carries `stop-cdu-A`, and the §6
> result is a test (`tests/test_procedures.py`).
> Written against commit `2ace733`, grammar v0.2.

## 1. The problem

Prescript borrows the HDL pipeline, but it is missing the layer where an HDL design actually lives.
In Verilog the engineer writes *behaviour* — a state machine, a datapath — and the tool lowers it
to gates. In Prescript v0.2 the engineer writes only *structure*: which nodes exist and how they
are wired. What those nodes **do** is not in the netlist at all. It is hard-coded in the engine:

| Behaviour                                | Where it is written today            |
| ---------------------------------------- | ------------------------------------ |
| A CDU drives circulation                 | `ir.py:34` `SOURCE_KINDS = {"cdu"}`  |
| `off` and `standby` stop flow            | `modes.py:17` `_DEAD_STATES`         |
| A valve conducts when `open`             | `modes.py:30` `ModeState.conducts`   |
| Accumulation stops at a load             | `ir.py:32` `LOAD_KINDS`              |
| The set of things that may exist at all  | `ir.py:18` `NodeKind` (a `Literal`)  |

Three consequences:

1. **The designer cannot describe a new component.** `NodeKind` is a closed `Literal` of six kinds.
   Adding an evaporator, a variable-speed pump or a three-way valve is a change to `ir.py` and
   `modes.py` — a change to the tool, not to the design.
2. **A kind can promise behaviour the engine does not have.** `check_valve` is in `DeviceKind` and
   is accepted by the loader, but no code anywhere distinguishes it from `valve`: outside this
   document the only occurrences of `check_valve` in the repository are the type declaration in
   `ir.py` and one line of `PRESCRIPT-LANGUAGE.md`. A non-return valve in a netlist today is a
   plain valve that reads as a non-return valve to a reviewer.
3. **Operating intent escapes into prose.** The reason a mode exists lives in its `note:` string —
   `"Concurrent maintainability: CDU-A isolated, CDU-B carries the whole hall"` — which nothing
   executes.

And the time axis is absent entirely. `modes:` are *static snapshots*: an override map plus
boundary conditions. In HDL terms they are test vectors, not a design. There is no way to write
"stop CDU-A" as the ordered procedure it is — stop the standby, stop the duty pump, stop the unit,
close the valves — and no way to ask what holds *between* those steps.

## 2. The line this proposal draws

The goal is that the engineer writes, in code, everything from the operating intent down to the
equivalent of RTL, and that everything below that line is computed.

```
operating intent        ──┐
  sequences, interlocks   │  written by the engineer, in the netlist   ← this proposal
  component state semantics ┘
──────────────────────────────────────────────────────────────────────
  named physical methods    ┐
  circulation and dead legs │  provided by the tool                    ← unchanged
  accumulation, screening   ┘
```

The split matters. In an HDL the engineer writes behaviour but never writes transistor physics —
the cell library and the synthesis tool own that. The same split here: **v0.3 lets the designer
declare roles, states and sequences; it does not let the designer write equations.** Darcy-Weisbach
stays in `checks/pressure_drop.py`, `Q = V · rho · cp · dT` stays in `checks/_util.py`, and
`AGENTS.md`'s "no physics we cannot defend" is untouched. A grammar that accepted arbitrary
constitutive equations would turn Prescript into an undefendable solver; that is explicitly not
proposed.

## 3. Part A — `kinds:`, the state semantics

Move the five hard-coded facts above into the netlist, as declarations.

```yaml
kinds:
  cdu:
    role: source            # drives circulation; where the loop is cut for accumulation
    states: {on: live, off: dead}
  pump:
    role: inline
    states: {on: live, off: dead, standby: dead}
  header:   {role: inline, states: {on: live, off: dead}}
  manifold: {role: inline, states: {on: live, off: dead}}
  rack:     {role: load,   states: {on: live, off: dead}}
  rdhx:     {role: load,   states: {on: live, off: dead}}

devices:
  valve:       {conducts_when: open, default_state: open}
  check_valve: {conducts_when: open, default_state: open, blocks_reverse: true}
```

`role` is a closed set the engine understands — `source`, `inline`, `load` — not free text; it is
the hook by which `modes.resolve` and `_util.accumulate` find flow sources and loop terminations.
A `states:` map labels each state `live` or `dead`. That is the whole of what is being externalised:
the vocabulary stays small on purpose.

**Shipped as a prelude.** `src/prescript/prelude/v0_3.yaml` holds exactly the block above, and a
netlist that declares no `kinds:` gets it implicitly. The acceptance test for Part A is therefore
sharp and cheap: `prescript verify examples/gb200-1su/netlist.yaml` must produce a byte-identical
report before and after. Part A adds no capability — it proves the semantics are expressible, and
it is the only honest way to find out whether the vocabulary above is sufficient.

Two things fall out of writing it down, both currently invisible:

- **`check_valve` gets a meaning or gets deleted.** `blocks_reverse: true` has to be implemented in
  `modes.resolve` (do not walk this edge backwards) or the kind must go. Today it silently lies.
- **The flow source is arguably the wrong node.** Physically the pump drives circulation, not the
  CDU; v0.2 works only because the pumps sit between `CDU-A` and `HDR-S-A` and a dead pump blocks
  propagation. Writing `role: source` next to `cdu` makes that modelling choice explicit and
  reviewable — it may be right (the CDU is where the loop is cut for accumulation) but it should be
  a decision on the page, not an artefact of edge direction.

## 4. Part B — `sequences:`, the ASM equivalent

A sequence is an ordered list of steps. Each step is a **delta** on the state of the previous one,
starting from a named mode.

```yaml
sequences:
  stop-cdu-A:
    from: normal
    intent: "Planned maintenance on CDU-A; the hall runs on CDU-B throughout"
    steps:
      - id: s1
        action: "Inhibit the standby pump"
        set: {PMP-A-2: off}
        done_when: {assume: "standby start inhibited at the controller", provenance: "assumed"}
      - id: s2
        action: "Stop the duty pump"
        set: {PMP-A-1: off}
        done_when: {assume: "loss of pump running feedback", provenance: "assumed"}
      - id: s3
        action: "Stop the CDU"
        set: {CDU-A: off}
      - id: s4
        action: "Isolate the pump branches"
        set: {V-PMP-A-1: closed, V-PMP-A-2: closed}
        within_s: 60
    holds: [C-01, C-05, C-06]          # must hold at every step
```

**A sequence elaborates into modes.** This is the whole mechanism, and it is why the proposal is
small: `loader` expands `stop-cdu-A` into `stop-cdu-A@s1 … @s4`, each a perfectly ordinary `Mode`
with the accumulated overrides. Everything downstream is unchanged — `modes.resolve`, every check
in `checks/`, the report matrix. `holds:` is sugar for naming those assertions in every elaborated
step. `prescript elaborate` prints the resolved absolute state per step, so the expansion is
reviewable.

In HDL terms: the ASM chart is written as a state sequence, each state is evaluated against the
netlist, and the existing assertions play the part of SVA sampled in every state.

**`done_when` is an assumption, not a computation.** The transition conditions in a real stop
sequence — "loss of pump running feedback", "valve to stop position within time limit" — are plant
feedback. Prescript cannot and must not pretend to evaluate them. They are recorded as `assume:`
with mandatory `provenance`, exactly like SystemVerilog's `assume` property: stated, carried into
the report, never silently treated as proven. Anything whose truth would need a transient
simulation is an assumption by construction.

## 5. Part C — assertions over transitions

Three new routines, all of which are about the sequence rather than a single state. All three start
life in `PLANNED` and return `UNRUN` until built, per `verification-semantics.md` rule 3.

| Routine          | Asks                                                                     |
| ---------------- | ------------------------------------------------------------------------ |
| `interlock`      | Does a named condition hold at **every** step of the sequence? (`holds:`) |
| `step_reachable` | Is every step reachable, and does the sequence terminate? No step whose `set:` contradicts a `done_when` assumption of an earlier step; no unreachable tail. The FSM reachability check. |
| `stroke_time`    | Does the sum of the declared actuation times on a step's `set:` fit inside its `within_s`? |

`stroke_time` is the one that touches time, so it is the one that must be tightest. It compares
**declared data against a declared budget** — a `stroke_s` attribute on the valve, with provenance,
against `within_s` on the step. It computes no dynamics. A valve with `stroke_s: null` makes the
check `UNRUN`, never `PASS`. Coast-down, thermal inertia and ride-through stay where they are
today: `ride_through` is in `PLANNED` (#30), and nothing here changes that.

### Relation to the dynamic-verification epic (#26)

Epic #26 adds time-domain simulation — a UVM-style testbench with lumped-parameter plant models and
a PID loop. This proposal adds no solver and no time integration, so the two do not compete; they
meet at `done_when`.

A `done_when: {assume: …}` is a stated, unproven precondition. Phase 3 of #26 — fault injection,
transfer times, rack inlet red-lines — is precisely the machinery that could **discharge** one: an
assumption the testbench reproduces stops being an assumption and becomes evidence. The static
behaviour layer is where those obligations get written down; the dynamic testbench is where some of
them later get paid. That is a reason to land this first, not after.

Two collisions to settle before both land:

- **The word "sequence" is taken twice.** In #26 a Sequence is constrained-random stimulus
  generation; here `sequences:` is a deterministic operating procedure. Both are standard usage in
  their own field. One of them should be renamed — `procedures:` here, or `scenarios:` there.
- **#27 plans to relax `AGENTS.md`'s "transient behaviour stays `UNRUN`"** into "a named simplified
  model is allowed". Nothing in this proposal depends on that rule either way: `stroke_time` compares
  two declared numbers, so it stays defensible under the old rule and the new one.

## 6. Evidence that the step layer finds something

Measured, not argued. I added the three steps of §4 as plain v0.2 modes to a copy of the reference
design and ran the existing `loading` checks against each of them, at the reference 150 kW/rack and
at the 200 kW/rack of the `ROADMAP.md` demo.

```
# 200 kW/rack
id    check          stopA-s1  stopA-s2  stopA-s3
S-02  loading(flow)  PASS      FAIL      FAIL
S-03  loading(heat)  PASS      FAIL      FAIL

FAIL S-02@stopA-s2: 11/26 elements over 100% of L/min rating
       - CDU-B 2602/2300 L/min (113%)
       - HDR-S-B 2602/2300 L/min (113%)
       - MAN-B-01 303/300 L/min (101%)
FAIL S-03@stopA-s2: 1/2 elements over 100% of kW rating
       - CDU-B 1720/1500 kW (115%)
```

`stopA-s2` is the step where the duty pump stops and **CDU-A is still running**. The hall is already
wholly on CDU-B there — the same 113% flow and 115% heat that `maint-cdu-A` reports — one step before
the mode that v0.2 models as the maintenance case. The end-state mode is not wrong; it is late. The
exposure window opens when the pump stops, and today nothing in the repository says so.

At 150 kW/rack every step passes, which is the other half of the result: the step layer does not
manufacture failures, it dates them.

(`stopA-s2` lists 11 elements and `stopA-s3` lists 12. The difference is a consequence of `CDU-A`
still being a live flow source at s2; it is worth understanding before Part A fixes `role: source`.)

## 7. Out of scope

Unchanged from `ROADMAP.md`, and worth restating because a behaviour layer invites all of it:
no transient or dynamic simulation, no control-logic synthesis, no pump curves, no PLC or DCS
export, no generation of equipment from a duty (that is high-level synthesis, two layers above
this), and no arbitrary user equations.

## 8. Staging

Three PRs, each independently reviewable; the first carries no new capability by design.

| PR   | Scope                                                                 | Exit criterion                                                    |
| ---- | --------------------------------------------------------------------- | ----------------------------------------------------------------- |
| v0.3a | `kinds:`/`devices:` + prelude; `ir.py` and `modes.py` read it         | reference report byte-identical; `check_valve` means something     |
| v0.3b | `sequences:` → elaborated modes; `elaborate` prints resolved steps    | the §6 steps live in the reference netlist, run by existing checks |
| v0.3c | `interlock`, `step_reachable`, `stroke_time`                          | each has a PASS, a FAIL and an UNRUN test                          |

Each PR changes `docs/PRESCRIPT-LANGUAGE.md` and the loader together, as `AGENTS.md` requires, and
bumps `prescript: 0.3` with v0.2 netlists still loading.

## 9. Open questions

1. **Is `role` a closed set of three enough?** A three-way diverting valve and a heat exchanger that
   couples two loops do not obviously fit `source`/`inline`/`load`.
2. **Should the pump be the source?** §3. Changing it would alter dead-leg results on every mode, so
   it needs its own PR and its own before/after.
3. **Cumulative or absolute step state?** Cumulative is proposed because it matches how procedures
   are written, but it makes a step unreadable in isolation. `elaborate` printing absolutes is the
   mitigation; it may not be enough for review.
4. **Do sequences belong in the netlist file at all?** They are operations, not plant. A separate
   `sequences.yaml` referencing the netlist may age better, and would keep `netlist.yaml` the single
   description of what is installed.
5. **Does a step need its own `conditions:`?** A stop sequence run on a summer afternoon is a
   different case from the same sequence in winter, and today `conditions` are per-mode.
6. **`sequences:` or `procedures:`?** §5 — the name clashes with the UVM Sequence of #26.
