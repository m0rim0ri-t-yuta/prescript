"""Dynamic verification: a UVM-style testbench around a time-domain plant model.

The static checks (`prescript verify`) gate a design before it gets here. This package drives a
plant model through time with constrained-random scenarios and judges the trace:

- `plant`: the device under test — a lumped-capacitance model integrated with scipy.
- `pid`: the controller the testbench closes the loop with.
- `uvm`: sequence item, sequence, driver, monitor, scoreboard and environment.
- `poc`: the Phase 1 testbench (one exchanger and one control valve, values `assumed`).

Every result names its method in `detail`; none of this is a study result.
"""
