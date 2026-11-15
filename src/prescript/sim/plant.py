"""Device under test: one CDU liquid-to-liquid exchanger with a control valve on the facility side.

Method (named in every result that uses it): two-node lumped capacitance on the secondary (rack)
side, a counterflow ε-NTU exchanger, a linear valve characteristic and a first-order valve
actuator, integrated with `scipy.integrate.solve_ivp` (RK45) between controller samples.

State `x = (t_return_c, t_supply_c, valve)`:

- `t_return_c` — the hot node: racks and return piping, heated by the IT load.
- `t_supply_c` — the cold node: exchanger secondary outlet and supply piping. This is the
  controlled temperature, the one the racks see at their inlet.
- `valve` — actual valve position, 0 (shut) to 1 (open).

Not modelled: pump dynamics (secondary flow is constant), transport delay, pressure, the facility
water plant (its supply temperature is a boundary condition), heat loss to the room.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.integrate import solve_ivp

METHOD = (
    "two-node lumped capacitance, counterflow ε-NTU exchanger, first-order valve actuator, "
    "solve_ivp RK45 between controller samples"
)


@dataclass(frozen=True)
class PlantParams:
    """Plant constants. `provenance` is mandatory, as it is for every rated element in a netlist."""

    secondary_lpm: float  # constant secondary (TCS) flow
    secondary_vol_heat_kj_lk: float  # rho*cp of the secondary coolant
    primary_max_lpm: float  # facility-water flow with the valve fully open
    primary_vol_heat_kj_lk: float  # rho*cp of facility water
    ua_kw_k: float  # exchanger conductance
    hot_volume_l: float  # coolant held in the hot node
    cold_volume_l: float  # coolant held in the cold node
    valve_tau_s: float  # actuator time constant
    provenance: str

    def __post_init__(self) -> None:
        if not self.provenance:
            raise ValueError("PlantParams needs a provenance (a source or the literal 'assumed')")
        for name in (
            "secondary_lpm",
            "secondary_vol_heat_kj_lk",
            "primary_max_lpm",
            "primary_vol_heat_kj_lk",
            "ua_kw_k",
            "hot_volume_l",
            "cold_volume_l",
            "valve_tau_s",
        ):
            if not getattr(self, name) > 0:
                raise ValueError(f"PlantParams.{name} must be positive")

    @property
    def secondary_kw_k(self) -> float:
        """Heat-capacity rate of the secondary flow, kW/K (= kJ/s/K)."""
        return self.secondary_lpm / 60.0 * self.secondary_vol_heat_kj_lk

    def primary_kw_k(self, valve: float) -> float:
        return valve * self.primary_max_lpm / 60.0 * self.primary_vol_heat_kj_lk


@dataclass(frozen=True)
class Inputs:
    """Boundary conditions held constant over one controller sample."""

    heat_kw: float
    facility_c: float
    valve_cmd: float


def effectiveness(ntu: float, cr: float) -> float:
    """Counterflow exchanger effectiveness from NTU and the capacity-rate ratio Cr = Cmin/Cmax."""
    if ntu <= 0:
        return 0.0
    if math.isclose(cr, 1.0, rel_tol=1e-9):
        return ntu / (1.0 + ntu)
    e = math.exp(-ntu * (1.0 - cr))
    return (1.0 - e) / (1.0 - cr * e)


def exchanger_kw(p: PlantParams, valve: float, t_hot_in: float, t_cold_in: float) -> float:
    """Heat moved from the secondary to the facility side at this valve position."""
    c_sec = p.secondary_kw_k
    c_pri = p.primary_kw_k(max(valve, 0.0))
    c_min, c_max = min(c_sec, c_pri), max(c_sec, c_pri)
    if c_min <= 0.0:
        return 0.0
    eps = effectiveness(p.ua_kw_k / c_min, c_min / c_max)
    return eps * c_min * (t_hot_in - t_cold_in)


def derivatives(p: PlantParams, u: Inputs, x: NDArray[np.float64]) -> NDArray[np.float64]:
    t_return, t_supply, valve = float(x[0]), float(x[1]), float(x[2])
    c_sec = p.secondary_kw_k
    q_hx = exchanger_kw(p, valve, t_return, u.facility_c)
    d_return = (u.heat_kw - c_sec * (t_return - t_supply)) / (
        p.hot_volume_l * p.secondary_vol_heat_kj_lk
    )
    d_supply = (c_sec * (t_return - t_supply) - q_hx) / (
        p.cold_volume_l * p.secondary_vol_heat_kj_lk
    )
    d_valve = (u.valve_cmd - valve) / p.valve_tau_s
    return np.array([d_return, d_supply, d_valve])


def step(p: PlantParams, u: Inputs, x: NDArray[np.float64], dt_s: float) -> NDArray[np.float64]:
    """Advance the plant by one controller sample with the inputs held (zero-order hold)."""
    sol = solve_ivp(
        lambda _t, y: derivatives(p, u, y), (0.0, dt_s), x, method="RK45", rtol=1e-6, atol=1e-8
    )
    if not sol.success:
        raise RuntimeError(f"solve_ivp failed: {sol.message}")
    return np.asarray(sol.y[:, -1], dtype=np.float64)


def capacity_kw(p: PlantParams, supply_c: float, facility_c: float) -> float:
    """Heat the exchanger removes with the valve fully open while holding `supply_c` (steady state).

    In steady state `t_return = supply + Q / c_sec` and `Q = ε·Cmin·(t_return - facility)`, which
    is linear in Q: `Q = k·(supply - facility) / (1 - k / c_sec)` with `k = ε·Cmin`.
    """
    k = exchanger_kw(p, 1.0, 1.0, 0.0)  # ε·Cmin at full stroke
    return k * (supply_c - facility_c) / (1.0 - k / p.secondary_kw_k)


def steady_state(
    p: PlantParams, heat_kw: float, supply_c: float, facility_c: float
) -> NDArray[np.float64]:
    """The state that holds `supply_c` at `heat_kw`, with the valve where it has to be.

    Raises ValueError when no valve position can hold it (the load exceeds the capacity).
    """
    t_return = supply_c + heat_kw / p.secondary_kw_k
    if heat_kw > capacity_kw(p, supply_c, facility_c):
        raise ValueError(f"{heat_kw:.1f} kW exceeds the capacity at {facility_c:.1f} °C water")
    lo, hi = 0.0, 1.0
    for _ in range(60):  # exchanger_kw is monotonic in the valve position
        mid = (lo + hi) / 2.0
        if exchanger_kw(p, mid, t_return, facility_c) < heat_kw:
            lo = mid
        else:
            hi = mid
    return np.array([t_return, supply_c, (lo + hi) / 2.0])
