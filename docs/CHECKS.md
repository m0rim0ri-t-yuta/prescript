# Assertion Routines

Status rules for every routine: `agent-config/rules/verification-semantics.md`.

## Implemented

| Routine        | Args                                  | PASS when                                                     | UNRUN when                         |
| -------------- | ------------------------------------- | ------------------------------------------------------------- | ---------------------------------- |
| `dual_path`    | `class`, `sides` (default `[A, B]`)   | every `dual_fed` load of `class` has a live feed from each side | no mode; no dual-fed loads          |
| `path_exists`  | `class`, `from?`                      | every load of `class` is energized (through `from`, if given)  | no mode; no loads of `class`        |
| `completeness` | `kinds`                               | every element of `kinds` has non-null `rating_*` (+ `break_ka` on breakers) | no element of `kinds`  |
| `coverage`     | —                                     | every non-meta assertion × mode cell ran (not `UNRUN`)        | nothing to cover                    |

## Planned (return `UNRUN: not implemented`)

| Routine            | Intent                                                                 | Milestone |
| ------------------ | ---------------------------------------------------------------------- | --------- |
| `loading`          | Per-mode load flow (demand × class) vs rating, kVA or A basis           | W2        |
| `n_minus_1`        | Remove each element of the swept kinds; critical loads keep a path     | W2        |
| `diverse_upstream` | A and B feeds of a critical load share no element up to `up_to`         | W2        |
| `standby_diverse`  | Duty and standby essential loads sit on different panels                | W2        |
| `generator_margin` | Generator kW ≥ essential + UPS recharge × factor                        | W2        |
| `time_margin`      | UPS battery minutes vs generator start / thermal limit                  | W2        |
| `consistency`      | Netlist values match the spec table                                    | W3        |
| `breaker_duty`     | Simplified fault-current screen vs `break_ka`, method named in result   | W3        |
