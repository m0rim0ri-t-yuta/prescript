# Prescript Netlist Language — v0.3

SSOT for the netlist format. `src/prescript/loader.py` implements it; change both in one PR.

## File

```yaml
prescript: 0.3            # grammar version (required); 0.2 still loads
project: <name>
units: {heat: kW, flow: L/min, temperature: C, pressure: kPa, length: mm, time: s}
fluids: {...}
blocks: {...}
nodes: [...]
edges: [...]
modes: {...}
procedures: {...}         # v0.3
assertions: [...]
```

**Versions**: `0.3` adds `procedures:`. A `0.2` netlist loads and verifies to the same report as
before; `procedures:` in a `0.2` netlist is an error that names the version. In either version a
mode name may no longer contain `@` (see Modes).

**Booleans are YAML 1.2**: only `true`/`false`. `on`, `off`, `yes`, `no` are plain strings, because
`on`/`off` are equipment states.

## Fluids

```yaml
fluids:
  pg25: {cp_kj_kgk: 3.85, density_kg_l: 1.03, viscosity_mpas: 2.0, provenance: "assumed: 25% PG"}
```

Every flow calculation uses `cp_kj_kgk × density_kg_l` as the `rho · cp` of `Q = V · rho · cp · dT`.
`viscosity_mpas` (dynamic viscosity at loop temperature) is used only by `pressure_drop`.
`provenance` is mandatory; any property may be `null`, which makes the checks that need it
`UNRUN`. A node names its fluid with `fluid: <name>`; naming an undeclared fluid is an error.

## Nodes

`{id, kind, state?, provenance?, ...attributes}`. Kinds: `cdu`, `pump`, `header`, `manifold`,
`rack`, `rdhx`. **Every** kind must carry `provenance`.

Attribute names carry units: `rating_kw`, `rating_lpm`, `rating_kpa`, `approach_k`, `heat_kw`,
`delta_t_k`, `max_inlet_c`, `return_min_c`, `return_max_c`, `dn_mm`, `length_m`, `roughness_mm`,
`dp_kpa`, `dp_lpm`, `volume_l`. An undecided value is `null`. The loader takes these at their
word: a unit-carrying attribute holds a number or `null`, and a string there is a netlist
error, not data — every check coerces these, so a typo caught at load time is a reported
error instead of a crash halfway through a run.

Loads (`rack`, `rdhx`): `class` (e.g. `it_liquid` | `it_air`), `heat_kw`, `delta_t_k`,
`max_inlet_c`, `dual_fed: true`.
CDUs: `rating_kw`, `rating_lpm`, `approach_k`, `return_min_c` / `return_max_c` (the return
temperature range the exchanger is selected for), `side: A|B`.
Pumps: `rating_lpm`, `rating_kpa` (the rated head: differential pressure at `rating_lpm`),
`standby_of: <id>`. A standby pump declares `state: standby`.
Headers: `rating_lpm`, and as pipe `dn_mm` (taken as the bore), `length_m`, `roughness_mm`,
`k_fittings` (the summed loss coefficient of the fittings on the run, dimensionless).
Manifolds: `rating_lpm`, `side: A|B`. Elsewhere the side is read from a whole `-A`/`-B` id segment.

Pressure drop of equipment (CDU exchanger, manifold, rack, rdhx) is a rated point: `dp_kpa` at a flow
of `dp_lpm`. At another flow it scales with the square of the flow.

Dynamics, read only by `prescript sim` (`docs/SIMULATION.md`); a `null` makes the simulation or the
judgement that needs it `UNRUN`. Pumps: `shutoff_kpa` (head at zero flow; with `rating_kpa` at
`rating_lpm` it fixes a quadratic curve), `npshr_m` (NPSH required at `rating_lpm`), `ramp_s` (speed
time constant on a start or stop). CDUs: `fill_kpa` (expansion-tank gauge pressure at the CDU
inlet), `facility_lpm` (facility-water flow with its valve fully open), `supply_c` (secondary
supply setpoint). Headers: `wave_speed_m_s` (pressure-wave speed), `design_kpa` (design pressure,
gauge). Valves: `stroke_s` (full stroke time; absent means instantaneous).

Coolant inventory, which `ride_through` counts, is `volume_l` on every element. A header states no
`volume_l`: its volume is its `dn_mm` bore over its `length_m` run, so it is geometry, not a second
number to keep in step.

Default state is `on`. Equipment states: `on`, `off`, `standby`. `off` and `standby` are dead: they
block flow.

## Edges

`{from, to, via?, share?, bidirectional?, role?}` — directed **the way the coolant travels**, so a
loop is a cycle: `cdu → pump → supply header → manifold → rack → return header → cdu`.
`via: {id, kind: valve|check_valve, state?: open|closed, kv_m3h?, provenance?}`. `kv_m3h` is the
flow coefficient: m³/h of water at a 1 bar drop.

A valve defaults to `open` and conducts while it is open — the opposite of a breaker.
`share` splits the quantity at a branch; it is used on both the supply and the return legs of a
dual-fed load.

## Blocks

```yaml
blocks:
  cdu_loop:
    params: {rating_lpm: 2300}
    provenance: "..."            # inherited by expanded nodes without their own
    expands_to: [ {id: "CDU-{s}", kind: cdu, rating_lpm: "{rating_lpm}"} ]
    edges:      [ {from: "CDU-{s}", to: "PMP-{s}-1"} ]
nodes:
  - {use: cdu_loop, s: A}        # instance args override params
```

A string that is exactly `"{param}"` keeps the parameter's type; otherwise it is formatted text.

## Modes

```yaml
modes:
  maint-cdu-A:
    overrides: {CDU-A: off, V-SA-01: closed}
    demand: {it_liquid: 1.0, it_air: 1.0}
    conditions: {facility_supply_c: 20}
    note: "..."
```

A mode name must not contain `@`: it is reserved for the modes procedures elaborate into.
`overrides` set equipment and valve states; the target must exist. `demand` is a load factor per
load class, applied to `heat_kw`. `conditions` carry the boundary the facility side imposes —
`facility_supply_c` is what `inlet_temp` and `return_temp` need, and a mode that omits it makes
those checks `UNRUN`. `loop_start_c` is the temperature of the water already in the loop at the
moment a mode's heat sink is lost — the facility side has failed in such a mode, so its supply
temperature cannot stand in for it; `ride_through` needs it.

## Procedures (v0.3)

An operating procedure written as the ordered sequence of states it moves the plant through — the
ASM-chart equivalent. Each step is a **delta** on the state the previous step left, starting from
a hand-written mode.

```yaml
procedures:
  stop-cdu-A:
    from: normal                       # required: an existing hand-written mode
    intent: "Planned maintenance on CDU-A; the hall runs on CDU-B throughout"   # optional
    holds: [C-01, C-05, C-06]          # optional: assertion ids asked at every step
    steps:                             # required, non-empty, in order
      - id: s1                         # required, unique in the procedure, [A-Za-z0-9_-]+
        action: "Inhibit the standby pump"     # required
        set: {PMP-A-2: off}            # required, non-empty: node or valve id -> state
        after_s: 30                    # optional, > 0: seconds after the previous step
        within_s: 60                   # optional, > 0
        done_when: {assume: "standby start inhibited at the controller", provenance: "assumed"}
```

A procedure name uses `[A-Za-z0-9_-]+`, like a step id. `set` targets must exist: a node takes
`on`, `off` or `standby`, a valve `open` or `closed`.

**Elaboration.** Step *k* becomes the ordinary mode `"<procedure>@<step id>"`. Its `overrides`
are the `from` mode's, updated by the `set:` of steps 1 … *k* in order — a later step wins. Its
`demand` and `conditions` are copied from the `from` mode, and its `note` is
`"<procedure> <step id>: <action>"`. The step modes follow the hand-written ones in `modes`, in
procedure and step order, so everything that reads a mode — every check, the report matrix,
`draw --mode` — reads them unchanged. `prescript elaborate` prints each step's absolute overrides.

**`holds:`** appends the procedure's step modes to the `modes` of each named assertion (once
each). It cannot name an assertion that runs on `static` or `meta`. An assertion may also name a
step mode directly, and `modes: all` includes every step mode.

**Time.** `after_s` is the time from the previous step (for the first step, from the start of the
procedure); `within_s` is the time the step is allowed to take. The static checks ignore both;
they are recorded for the simulator.

**`done_when` is an assumption, not a computation.** It states the plant feedback that ends the
step — SystemVerilog's `assume`. `provenance` is mandatory. Nothing evaluates it: `prescript
verify` prints every one under the summary as `assumed`, so a PASS at a step is never read as proof
that the plant reached it.

## Spec tables

```yaml
spec:
  02_Loads:
    provenance: "RA11338001 (S-21): the load schedule this netlist was built from"
    rows:
      - {id: RACK-01, heat_kw: 150, delta_t_k: 10, max_inlet_c: 45}
```

`spec` carries the sheets the design was taken from, transcribed: one table per sheet name, one row
per element `id`, and a field name that is the attribute name on the node. `provenance` is
mandatory, ids are unique within a table, and a cell the spec has not decided is `null`.

The tables are not part of the design — nothing is elaborated from them and no check reads them for
a value. `consistency` compares them with the elaborated netlist, which is what catches a block
parameter edited by hand: eight racks move, and only the schedule still says 150 kW.

## Assertions

`{id, check, args, modes, severity?}`. `modes` is `all` (every mode, procedure steps included),
or a list of mode names and/or the pseudo-modes `static` (runs once on the design) and `meta` (runs
over the other results). A procedure's `holds:` adds its step modes to the list.
`severity: warn` turns a `FAIL` into a `WARN`. Routine semantics: `CHECKS.md`.
