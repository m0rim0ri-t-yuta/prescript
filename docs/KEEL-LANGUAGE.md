# Keel Netlist Language — v0.1

SSOT for the netlist format. `src/keel/loader.py` implements it; change both in one PR.

## File

```yaml
keel: 0.1            # grammar version (required)
project: <name>
units: {power: kW, apparent: kVA, voltage: kV, current: A, fault: kA, time: s}
blocks: {...}
nodes: [...]
edges: [...]
modes: {...}
assertions: [...]
```

**Booleans are YAML 1.2**: only `true`/`false`. `on`, `off`, `yes`, `no` are plain strings, because
`on`/`off` are equipment states.

## Nodes

`{id, kind, state?, provenance?, ...attributes}`. Kinds: `source`, `transformer`, `bus`, `panel`,
`ups`, `generator`, `ats`, `rack_pdu`, `load`. Kinds `source`, `transformer`, `bus`, `panel`, `ups`,
`generator`, `load` **must** carry `provenance`.

Attribute names carry units: `rating_kva`, `rating_a`, `rating_kw`, `voltage_kv`, `z_pct`,
`battery_min`, `start_time_s`, `rated_kw`. An undecided value is `null`.

Loads: `class` (`critical` | `essential`), `dual_fed: true`, `standby_of: <id>`.
ATS: `sources: [a, b]`, `preferred: a`. The loader creates one synthetic edge per source.
Rack PDUs: `side: A|B`. Elsewhere the side is read from a whole `-A`/`-B` id segment.

Default states: `generator` → `off`; everything else → `on`. UPS states: `on`, `bypass`, `battery`,
`off`.

## Edges

`{from, to, via?, share?, bidirectional?, role?}` — directed supply → load.
`via: {id, kind: breaker|switch, state?: closed|open, rating_a?, break_ka?, provenance?}`.
`role`: `rectifier_input` / `bypass_input` for UPS inputs.

## Blocks

```yaml
blocks:
  ups_block:
    params: {rating_kva: 1500}
    provenance: "..."            # inherited by expanded nodes without their own
    expands_to: [ {id: "UPS-{s}", kind: ups, rating_kva: "{rating_kva}"} ]
    edges:      [ {from: "LVMSB-{s}", to: "UPS-{s}"} ]
nodes:
  - {use: ups_block, s: A}       # instance args override params
```

A string that is exactly `"{param}"` keeps the parameter's type; otherwise it is formatted text.

## Modes

```yaml
modes:
  maint-A:
    overrides: {TR-A: off, CB-EM-B: closed, ATS-01: {select: GEN-01}}
    demand: {critical: 1.0, essential_duty: 1.0, essential_standby: 1.0}
    note: "..."
```

Override targets must exist. `{select: X}` applies only to an `ats`, and `X` must be one of its
sources. `demand` is carried for the loading checks (not used in v0.1 routines).

## Assertions

`{id, check, args, modes, severity?}`. `modes` is `all`, or a list of mode names and/or the
pseudo-modes `static` (runs once on the design) and `meta` (runs over the other results).
`severity: warn` turns a `FAIL` into `WARN`. Routine semantics: `CHECKS.md`.
