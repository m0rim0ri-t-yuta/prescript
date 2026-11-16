"""Phase 2 testbench constants (#45): the controller, sampling and the random envelope.

The plant comes from the netlist; these are the testbench's own choices, all `assumed`. The
controller is one PI loop per running CDU on its facility-water valve, holding the CDU's secondary
supply at its `supply_c`.
"""

from __future__ import annotations

from prescript.sim.netbench import Controls, Envelope

CONTROLS = Controls(
    kp=0.05,  # facility valve stroke per K
    ti_s=60.0,
    valve_tau_s=5.0,
    dt_s=1.0,
    warmup_s=1200.0,
    settled_k=0.05,
)

# Random runs: each gap between procedure steps stretched 0.5-1.5x, the IT load moving between
# 60 % and 100 % of the mode's demand every 2-5 minutes, the facility water up to 2 K either side
# of the mode's value and drifting across the run, and 10 minutes after the last step.
ENVELOPE = Envelope(
    step_jitter=(0.5, 1.5),
    it_factor=(0.6, 1.0),
    it_hold_s=(120, 300),
    facility_offset_k=(-2.0, 2.0),
    settle_s=600.0,
)
