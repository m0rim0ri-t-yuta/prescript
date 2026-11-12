# Assertion Routines

Status rules for every routine: `agent-config/rules/verification-semantics.md`.

## Implemented

| Routine        | Args                                  | PASS when                                                     | UNRUN when                         |
| -------------- | ------------------------------------- | ------------------------------------------------------------- | ---------------------------------- |
| `dual_path`    | `class`, `sides` (default `[A, B]`)   | every `dual_fed` load of `class` has a live feed from each side | no mode; no dual-fed loads          |
| `path_exists`  | `class`, `from?`                      | every load of `class` is energized (through `from`, if given)  | no mode; no loads of `class`        |
| `completeness` | `kinds`                               | every element of `kinds` has non-null `rating_*` (+ `break_ka` on breakers) | no element of `kinds`  |
| `coverage`     | —                                     | every non-meta assertion × mode cell ran (not `UNRUN`)        | nothing to cover                    |
| `loading`      | `kind`, `limit`, `basis?` (`kva`/`amps`), `pf?` | every element of `kind` carries ≤ `limit` × rating in the mode | no mode; no element of `kind`; any rating, voltage, `pf`, `rated_kw` or demand factor it needs is missing (unless something already FAILs) |

## Planned (return `UNRUN: not implemented`)

| Routine            | Intent                                                                 | Milestone |
| ------------------ | ---------------------------------------------------------------------- | --------- |
| `n_minus_1`        | Remove each element of the swept kinds; critical loads keep a path     | W2        |
| `diverse_upstream` | A and B feeds of a critical load share no element up to `up_to`         | W2        |
| `standby_diverse`  | Duty and standby essential loads sit on different panels                | W2        |
| `generator_margin` | Generator kW ≥ essential + UPS recharge × factor                        | W2        |
| `time_margin`      | UPS battery minutes vs generator start / thermal limit                  | W2        |
| `consistency`      | Netlist values match the spec table                                    | W3        |
| `breaker_duty`     | Simplified fault-current screen vs `break_ka`, method named in result   | W3        |

## `loading` method

Flow: `prescript.flow` — a **lossless radial flow**, named in every result's `detail`.

1. Demand per load = `rated_kw` × the mode's `demand` factor for its class: `critical`;
   `essential_standby` for an essential load with `standby_of`; `essential_duty` otherwise.
2. Each node's throughput is split over its **live** feeds by `share`, renormalised over the feeds
   that are live in this mode (equal split when no share is given). So when side A is down, a
   dual-fed rack draws its whole demand from side B.
3. A bidirectional edge (bus tie) is used only when the node has no other live feed.
4. Live sources (utility, running generator, UPS on battery) absorb what reaches them.
5. Losses, UPS recharge and reactive flow are ignored.

Conversion: kVA = kW / pf; A = kW / (√3 × `voltage_kv` × pf). `pf` comes from the element's own
`pf` attribute, else the assertion's `pf` argument. Default basis: `rating_kva` → kVA, else
`rating_a` → A.

A result is `FAIL` when any element exceeds the limit — even if other elements lack data, which are
still listed in `missing`. Otherwise any missing value makes it `UNRUN`; only a complete,
in-limit set is `PASS`.
