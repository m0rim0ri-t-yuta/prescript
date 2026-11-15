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
| `return_temp`  | `kinds` (default `[cdu]`)                         | the mixed return at every running CDU stays within `return_min_c`–`return_max_c` | no mode; no CDUs; the mode sets no `facility_supply_c`; nothing circulating; any null input |
| `pressure_drop` | `method` (`darcy_weisbach`), `limit` (default 1.0), `available_kpa?` | every load's loop drops no more than `limit` × the head of the pump on it (or `available_kpa`) | no mode; unknown method; nothing circulating; any null input, or a supply leg with no pump |
| `ride_through` | `class`, `must_exceed_s` | every loop that carries the class holds it for longer than `must_exceed_s` | no mode; no loads of `class`; no `must_exceed_s`; the mode sets no `loop_start_c`; any null inventory or load input |
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
(`pressure_drop`).

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
flow around a bottleneck — that needs a network solution, and `pressure_drop` is a screening too.

### How `pressure_drop` adds up a loop

A load's loop is one of its supply legs, the load, and the worst of its return legs, each element at
the flow `accumulate` gives it in this mode (every circulating load counted):

| Element                              | Drop                                                           | Inputs                                                   |
| ------------------------------------ | -------------------------------------------------------------- | -------------------------------------------------------- |
| header (pipe)                        | Darcy-Weisbach `(f·L/D + ΣK)·rho·v²/2`, f by Swamee-Jain (64/Re below Re 2300) | `dn_mm` (taken as the bore), `length_m`, `roughness_mm`, `k_fittings`; fluid `density_kg_l`, `viscosity_mpas` |
| CDU exchanger, manifold, rack, RDHX  | rated drop scaled by flow squared, `dp_kpa · (Q / dp_lpm)²`    | `dp_kpa`, `dp_lpm`                                       |
| valve                                | `100 · SG · (Q / Kv)²` kPa, Q in m³/h                          | `kv_m3h`; SG from the fluid's `density_kg_l`             |
| pump                                 | adds its rated head, `rating_kpa`, at any flow                 | `rating_kpa`                                             |

Each supply leg is compared with the head of the pump on it; the result names the worst leg of each
load (`RACK-01 via PMP-B-1: 253/250 kPa (101%)`). It is a screening: the whole header flow is taken
over the whole header length, which over-states the drop at the far end of a main; the pump gives
one rated point, not a curve; parallel paths are not balanced against each other; one fluid, single
phase, steady state. The method is named in every result.

### How `return_temp` mixes

Each load's outlet is its inlet — facility supply plus the approach of the CDU that serves it, the
same stack-up as `inlet_temp` — plus its `delta_t_k`. The outlets are mixed in proportion to the
flow each load sends back to each CDU, along the return legs and shares `accumulate` uses, so a rear
door at a wider `dT` (and so less flow) pulls the mix less than a rack. A demand factor scales flow,
not temperature rise, so in this model a heavier load does not warm the return; the facility
temperature, the approach and each load's design `dT` do. Heat gained or lost along the pipes and
bypass control are not modelled. A stopped CDU receives nothing and is not judged.
### How `ride_through` counts the inventory

One lumped volume at one temperature, the heat sink gone and the pumps still turning:

| Term      | From                                                                                     |
| --------- | ---------------------------------------------------------------------------------------- |
| inventory | `volume_l` of every element hydraulically connected to the load through the valves this mode leaves open; a header's volume is its `dn_mm` bore over its `length_m` run |
| heat      | `heat_kw` × the mode's demand factor for **every** load on that loop, whatever its class — they all warm the same water |
| headroom  | the mode's `loop_start_c` up to the tightest `max_inlet_c` among the loads **of the class under test** |
| time      | `V · rho · cp · ΔT / Q`, reported against `must_exceed_s`                                 |

A shut valve splits the inventory, so an isolated branch is judged on what is left inside it. The
metal mass of pipes, plates and exchangers is ignored, which under-states the time; heat lost to the
hall is ignored, which over-states it. It is one temperature, not a profile, and it does not ask
whether the pumps are on a UPS — it assumes only the heat rejection was lost. The method is named in
every result.

## Planned (return `UNRUN: not implemented`)

| Routine          | Intent                                                                   | Milestone |
| ---------------- | ------------------------------------------------------------------------ | --------- |
| `leak_isolation` | Every branch can be isolated without stopping a load that is still running | W3       |
| `consistency`    | Netlist values match the spec table                                       | W3        |
