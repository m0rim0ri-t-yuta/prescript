# Assertion Routines

Status rules for every routine: `agent-config/rules/verification-semantics.md`.

## Implemented

| Routine        | Args                                              | PASS when                                                              | UNRUN when                                        |
| -------------- | ------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------- |
| `loop_closed`  | `class`, `via?`                                   | every load of `class` sits on a closed loop back to a CDU (through `via`, if given) | no mode; no loads of `class`          |
| `dual_path`    | `class`, `sides` (default `[A, B]`)               | every `dual_fed` load of `class` has a live feed from each side        | no mode; no dual-fed loads                        |
| `loading`      | `basis` (`flow`\|`heat`), `kinds`, `limit`        | no element of `kinds` carries more than `limit` × its rating           | no mode; no elements; nothing circulating; any null rating or load input |
| `inlet_temp`   | `class`                                           | facility supply + CDU approach stays under each load's `max_inlet_c`   | no mode; no loads; the mode sets no `facility_supply_c`; any null input  |
| `n_minus_1`    | `class`, `sweep` (kinds; default every non-load kind) | every load of `class` keeps a closed loop with any one swept element stopped | no mode; no loads of `class`; nothing of the swept kinds carries flow |
| `balance`      | `class`, `tolerance_pct` (default 10)             | every load of `class` gets its required flow, short by no more than `tolerance_pct` | no mode; no loads of `class`; nothing circulating; any null rating or load input |
| `completeness` | `kinds`                                           | every element of `kinds` has non-null `rating_*` (+ `kv_m3h` on valves) | no element of `kinds`                            |
| `coverage`     | —                                                 | every non-meta assertion × mode cell ran (not `UNRUN`)                 | nothing to cover                                  |

### How `loading` gets its numbers

A load's flow comes from the steady-state sensible-heat balance `Q = V · rho · cp · dT`, with
`rho · cp` taken from the `fluids:` entry the load names and `dT` from its `delta_t_k`. Each load's
flow (or heat) is then walked around its own loop — up the supply side to the CDU that drives it,
and down the return side back to that CDU — splitting by the edge `share` at every branch. Paths
through another load are not traversed, and a dead leg carries nothing.

This is a steady-state balance, not a hydraulic solution: it says how much has to pass through an
element, not whether each load gets its share (`balance`) or whether the pump can push it there
(`pressure_drop`, not built yet).

### What `n_minus_1` sweeps

The sweep stops one element at a time, resolves the mode again and applies the same loop test as
`loop_closed`. It covers only the elements that carry flow in that mode: a standby pump, a dead leg
or the side a maintenance mode has already taken out has nothing left to drop, so stopping it could
not change a result — and counting it would overstate how much redundancy was proved. Loads are
never swept; they are what the sweep protects. One element at a time, nodes only: N-2 and valve
sweeps are out of scope.

### How `balance` screens

A load's requirement is split over its supply legs, and separately over its return legs, by edge
`share` — the same split `loading` uses. A leg can deliver only what the tightest rating on it
allows: its share is scaled by `min(1, rating_lpm / carried)` of its most loaded element, where
`carried` counts every circulating load, not only the class under test. What the load gets is the
sum over its legs, limited by the worse of the two sides. The method is named in every result.

This is a rating-limited screening, not a hydraulic solution. It never delivers more than the
requirement, so it only catches shortfalls, and it cannot say how a real loop would redistribute
flow around a bottleneck — that needs the pressure solution `pressure_drop` will give.

## Planned (return `UNRUN: not implemented`)

| Routine          | Intent                                                                   | Milestone |
| ---------------- | ------------------------------------------------------------------------ | --------- |
| `pressure_drop`  | 1-D pipe network against the pump curve, method named in the result       | W2        |
| `return_temp`    | Mixed return temperature at the CDU against its design range              | W2        |
| `ride_through`   | Loop thermal mass vs the time the IT load can be carried without cooling  | W3        |
| `leak_isolation` | Every branch can be isolated without stopping a load that is still running | W3       |
| `consistency`    | Netlist values match the spec table                                       | W3        |
