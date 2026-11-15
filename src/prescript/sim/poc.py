"""Phase 1 testbench (#27): one CDU exchanger and one facility-side PID valve.

Every value is `assumed` — round numbers in the range of a single GB200 NVL72 rack loop, not a
product's datasheet. The secondary coolant is the reference design's PG25
(`examples/gb200-1su/netlist.yaml`, fluids.pg25: cp 3.85 kJ/(kg·K), density 1.03 kg/L).
"""

from __future__ import annotations

from prescript.sim.pid import Pid
from prescript.sim.plant import PlantParams
from prescript.sim.uvm import Bench, Constraints, Criteria

PLANT = PlantParams(
    secondary_lpm=300.0,
    secondary_vol_heat_kj_lk=3.85 * 1.03,
    primary_max_lpm=200.0,
    primary_vol_heat_kj_lk=4.18,
    ua_kw_k=30.0,
    hot_volume_l=100.0,
    cold_volume_l=100.0,
    valve_tau_s=5.0,
    provenance="assumed",
)

CRITERIA = Criteria(setpoint_c=40.0, band_k=0.5, settle_s=300.0, hold_s=120.0)

# The envelope a regression draws from: up to one rack's 150 kW, facility water 24-32 °C.
ENVELOPE = Constraints(heat_kw=(30.0, 150.0), facility_c=(24.0, 32.0), step_at_s=(60, 180))


def controller() -> Pid:
    return Pid(kp=0.1, ti_s=20.0)


BENCH = Bench(plant=PLANT, controller=controller, criteria=CRITERIA, dt_s=1.0, duration_s=900.0)
