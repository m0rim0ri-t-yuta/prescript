"""Heat carried round the network: one well-mixed volume per netlist node (Phase 2, #45).

Each node holds `volume_l` of coolant (a header's comes from its bore and run, as in
`ride_through`) at one temperature. A junction holds nothing: it mixes what arrives, weighted by
flow, and a valve passes its inlet temperature on. With the flows held over a sample the node
temperatures obey a linear system,

    C_n dT_n/dt = c * q_n * (T_in(n) - T_n) + Q_n - kappa_n * (T_in(n) - T_facility)

where `c` is the coolant's `rho * cp`, `q_n` the flow through the node, `T_in(n)` the junction it
draws from, `Q_n` the heat a load puts in, and `kappa_n = ε * Cmin` the CDU exchanger's conductance
to the facility water (counterflow ε-NTU on the CDU's inlet temperature; zero elsewhere). It is
integrated exactly over the sample with a matrix exponential. A node with no flow through it keeps
its heat: a rack whose coolant has stopped warms at `Q / C`.

Not modelled: transport delay along a pipe (each volume is mixed), heat loss to the room, the
facility water plant (its supply temperature is a boundary condition).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.linalg import expm

from prescript.checks.ride_through import _volume_l
from prescript.sim.network import Network, NetworkError, Solution

METHOD = (
    "lumped advection network (one mixed volume per node, flow-weighted mixing at junctions), "
    "counterflow ε-NTU CDU exchangers with UA from the rated point, exact (matrix exponential) "
    "integration between samples"
)

FACILITY_KJ_LK = 4.18  # facility water, rho * cp


def effectiveness(ntu: float, cr: float) -> float:
    """Counterflow exchanger effectiveness from NTU and Cr = Cmin / Cmax."""
    if ntu <= 0.0:
        return 0.0
    if math.isclose(cr, 1.0, rel_tol=1e-9):
        return ntu / (1.0 + ntu)
    e = math.exp(-ntu * (1.0 - cr))
    return (1.0 - e) / (1.0 - cr * e)


def ntu_for(eps: float, cr: float) -> float:
    """The inverse of `effectiveness` for a counterflow exchanger."""
    if not 0.0 < eps < 1.0:
        raise ValueError(f"effectiveness {eps:.3f} is outside (0, 1)")
    if math.isclose(cr, 1.0, rel_tol=1e-9):
        return eps / (1.0 - eps)
    return math.log((1.0 - eps * cr) / (1.0 - eps)) / (1.0 - cr)


@dataclass(frozen=True)
class Exchanger:
    """A CDU's liquid-to-liquid exchanger, sized from its rated point."""

    ua_kw_k: float
    facility_kw_k: float  # facility-water capacity rate with its valve fully open

    def kappa(self, secondary_kw_k: float, valve: float) -> float:
        """`ε * Cmin`, kW/K: heat moved per kelvin between the secondary inlet and the water."""
        c_pri = max(valve, 0.0) * self.facility_kw_k
        c_min, c_max = min(secondary_kw_k, c_pri), max(secondary_kw_k, c_pri)
        if c_min <= 1e-9:
            return 0.0
        return effectiveness(self.ua_kw_k / c_min, c_min / c_max) * c_min


@dataclass
class Thermal:
    net: Network
    nodes: list[str]
    capacity: NDArray[np.float64]  # kJ/K per node
    c: float  # coolant rho * cp, kJ/(L K)
    exchangers: dict[str, Exchanger]
    missing: tuple[str, ...]


def build(net: Network) -> Thermal:
    missing: list[str] = []
    c = net.fluid.volumetric_heat_kj_lk()
    if c is None:
        missing.append(f"fluid {net.fluid.name}.cp_kj_kgk/density_kg_l")
    nodes = list(net.design.nodes)
    caps = []
    for nid in nodes:
        volume = _volume_l(net.design.nodes[nid])
        if volume is None:
            missing.append(f"{nid}.volume_l")
        caps.append((volume or 0.0) * (c or 0.0))
    exchangers: dict[str, Exchanger] = {}
    for cdu in net.design.nodes_of("cdu"):
        need = ("rating_kw", "rating_lpm", "approach_k", "facility_lpm")
        values = [cdu.get(k) for k in need]
        gaps = [f"{cdu.id}.{k}" for k, v in zip(need, values, strict=True) if v is None]
        if gaps or c is None:
            missing += gaps
            continue
        q_r, lpm, approach, fac_lpm = (float(v) for v in values)
        c_sec = lpm / 60.0 * c
        c_pri = fac_lpm / 60.0 * FACILITY_KJ_LK
        c_min, c_max = min(c_sec, c_pri), max(c_sec, c_pri)
        # rated point: secondary supply = facility + approach, return = supply + Q / C_sec
        eps = q_r / (c_min * (approach + q_r / c_sec))
        try:
            ua = ntu_for(eps, c_min / c_max) * c_min
        except ValueError as exc:
            raise NetworkError(f"{cdu.id}: no exchanger meets its rated point ({exc})") from exc
        exchangers[cdu.id] = Exchanger(ua_kw_k=ua, facility_kw_k=c_pri)
    return Thermal(net, nodes, np.array(caps), c or 0.0, exchangers, tuple(missing))


@dataclass(frozen=True)
class Boundary:
    """Inputs held over one sample."""

    heat_kw: dict[str, float]  # load id -> kW into the coolant
    facility_c: float
    cdu_valve: dict[str, float]  # running CDU id -> facility valve position 0..1


def inlet_map(th: Thermal, sol: Solution) -> tuple[NDArray[np.float64], list[int], list[float]]:
    """Junction temperatures as a linear map of node temperatures: `T_j = M @ T_nodes`.

    Also returns, per node, the junction it draws from and the flow through it (L/s, >= 0).
    """
    net = th.net
    n_j = len(net.junctions)
    pos = {nid: i for i, nid in enumerate(th.nodes)}
    w_jn = np.zeros((n_j, len(th.nodes)))
    w_jj = np.zeros((n_j, n_j))
    inflow = np.zeros(n_j)
    for e in net.elements:
        q = sol.flow[e.id]
        if abs(q) < 1e-9:
            continue
        src, dst = (e.a, e.b) if q > 0 else (e.b, e.a)
        inflow[dst] += abs(q)
        if e.node is not None:
            w_jn[dst, pos[e.node.id]] += abs(q)
        else:
            w_jj[dst, src] += abs(q)
    for j in range(n_j):
        if inflow[j] > 0:
            w_jn[j] /= inflow[j]
            w_jj[j] /= inflow[j]
    m = np.linalg.solve(np.eye(n_j) - w_jj, w_jn)
    draws, flows = [], []
    for nid in th.nodes:
        e = net.element(nid)
        q = sol.flow[nid]
        draws.append(e.a if q >= 0 else e.b)
        flows.append(abs(q) / 60.0)
    return m, draws, flows


def advance(
    th: Thermal, sol: Solution, temps: NDArray[np.float64], u: Boundary, dt_s: float
) -> NDArray[np.float64]:
    """Node temperatures after `dt_s` with flows and inputs held."""
    m, draws, flows = inlet_map(th, sol)
    n = len(th.nodes)
    a = np.zeros((n + 1, n + 1))
    for i, nid in enumerate(th.nodes):
        cap = th.capacity[i]
        if cap <= 0.0:
            continue
        g = th.c * flows[i]  # kW/K carried through the node
        kappa = 0.0
        if nid in u.cdu_valve and nid in th.exchangers:
            kappa = th.exchangers[nid].kappa(g, u.cdu_valve[nid])
        a[i, :n] += (g - kappa) * m[draws[i]] / cap
        a[i, i] -= g / cap
        a[i, n] = (u.heat_kw.get(nid, 0.0) + kappa * u.facility_c) / cap
    out = expm(a * dt_s) @ np.append(temps, 1.0)
    return np.asarray(out[:n], dtype=np.float64)


def junction_temps(th: Thermal, sol: Solution, temps: NDArray[np.float64]) -> NDArray[np.float64]:
    m, _, _ = inlet_map(th, sol)
    return np.asarray(m @ temps, dtype=np.float64)


def exchanger_kw(
    th: Thermal,
    sol: Solution,
    temps: NDArray[np.float64],
    cdu: str,
    valve: float,
    facility_c: float,
) -> float:
    """Heat a CDU moves to the facility water at this state."""
    if cdu not in th.exchangers:
        return 0.0
    m, draws, flows = inlet_map(th, sol)
    i = th.nodes.index(cdu)
    t_in = float(m[draws[i]] @ temps)
    kappa = th.exchangers[cdu].kappa(th.c * flows[i], valve)
    return kappa * (t_in - facility_c)
