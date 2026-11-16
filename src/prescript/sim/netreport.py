"""Render Phase 2 runs: a per-state timeline of the nominal run, the run table, a CSV trace and an
SVG chart. Rendering only; every verdict comes from `netbench.Scoreboard`."""

from __future__ import annotations

import csv
import io
import math
from html import escape

from prescript import report
from prescript.ir import LOAD_KINDS, Design
from prescript.result import Status
from prescript.sim import netbench
from prescript.sim.netbench import Run, Trace
from prescript.sim.network import Network

_IDS = ("P-01", "P-02", "P-03")


def segments(tr: Trace) -> list[tuple[int, int]]:
    """Sample ranges [start, end) over which the active state (label) does not change."""
    out, start = [], 0
    for k in range(1, len(tr.t) + 1):
        if k == len(tr.t) or tr.label[k] != tr.label[start]:
            out.append((start, k))
            start = k
    return out


def _timeline(design: Design, net: Network, tr: Trace) -> list[str]:
    cdus = [c.id for c in design.nodes_of("cdu")]
    loads = [n.id for n in design.nodes.values() if n.kind in LOAD_KINDS]
    pumps = [p.id for p in design.nodes_of("pump")]
    head = "t [s]  state" + " " * 22 + "".join(f"{c + ' L/min':>14}" for c in cdus)
    out = [head + "  least NPSH margin      hottest load"]
    for k0, k1 in segments(tr):
        flows = "".join(f"{tr.series(c)[k1 - 1]:14.0f}" for c in cdus)
        margins = [
            (j[0] - j[1], p, k)
            for k in range(k0, k1)
            for p in pumps
            if (j := netbench.npsh(net, tr, k, p)) is not None
        ]
        if margins:
            m, p, _ = min(margins)
            npsh = f"{p} {m:+.1f} m"
        else:
            npsh = "n/a"
        temps = [(netbench.load_temp(net, tr, k, n)[0], n) for k in range(k0, k1) for n in loads]
        hot = max(temps) if temps else (math.nan, "-")
        out.append(
            f"{tr.t[k0]:5.0f}  {tr.label[k0][:26]:26}{flows}  {npsh:22} {hot[1]} {hot[0]:.1f} °C"
        )
    return out


def to_text(
    runs: list[Run],
    design: Design,
    net: Network | None,
    title: str,
    verbose: bool = False,
) -> str:
    results = [r for run in runs for r in run.results]
    out = [f"prescript sim — Phase 2 testbench on {design.project}, {title}"]
    out.append(f"method: {netbench.METHOD}")
    nominal = runs[0] if runs else None
    if nominal is not None and nominal.trace is not None and net is not None:
        out += ["", f"timeline of {nominal.scenario.run} (values at the end of each state):"]
        out += _timeline(design, net, nominal.trace)
    out += ["", "run     " + "".join(f"{i:7}" for i in _IDS) + "scenario"]
    for run in runs:
        by_id = {r.assertion: r.status.value for r in run.results}
        cells = "".join(f"{by_id.get(i, '-'):7}" for i in _IDS)
        out.append(f"{run.scenario.run}  {cells}{run.scenario.describe()}")
    out += ["", report.summary(results)]
    shown = [r for r in results if verbose or r.status is not Status.PASS]
    seen: set[tuple[str, str]] = set()
    if shown:
        out.append("")
    for r in shown:
        detail = r.detail.split("; method: ", 1)[0]
        key = (r.assertion, detail + "".join(r.offending))
        if key in seen and not verbose:
            continue  # the same finding in another random run says nothing new
        seen.add(key)
        out.append(f"{r.status.value:5}  {r.assertion}@{r.mode}: {detail}")
        out += [f"         - {item}" for item in r.offending]
        out += [f"         - missing: {item}" for item in r.missing]
    return "\n".join(out)


def to_csv(design: Design, net: Network, tr: Trace) -> str:
    pumps = [p.id for p in design.nodes_of("pump")]
    cdus = [c.id for c in design.nodes_of("cdu")]
    loads = [n.id for n in design.nodes.values() if n.kind in LOAD_KINDS]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        ["t_s", "state", "heat_kw", "facility_c"]
        + [f"flow_lpm:{e}" for e in tr.elements]
        + [f"temp_c:{n}" for n in tr.nodes]
        + [f"load_c:{n}" for n in loads]
        + [f"suction_kpag:{p}" for p in pumps]
        + [f"npsha_m:{p}" for p in pumps]
        + [f"speed:{p}" for p in pumps]
        + [f"facility_valve:{c}" for c in cdus]
    )
    for k in range(len(tr.t)):
        row: list[object] = [f"{tr.t[k]:.0f}", tr.label[k], f"{tr.heat_kw[k]:.1f}"]
        row.append(f"{tr.facility_c[k]:.2f}")
        row += [f"{v:.1f}" for v in tr.flow[k]]
        row += [f"{v:.3f}" for v in tr.temps[k]]
        row += [f"{netbench.load_temp(net, tr, k, n)[0]:.3f}" for n in loads]
        row += [f"{tr.pressure[k][net.element(p).a]:.2f}" for p in pumps]
        row += [
            f"{j[0]:.2f}" if (j := netbench.npsh(net, tr, k, p)) is not None else "" for p in pumps
        ]
        row += [f"{tr.speed[k][p]:.3f}" for p in pumps]
        row += [f"{tr.fac_valve[k][c]:.3f}" for c in cdus]
        w.writerow(row)
    return buf.getvalue()


# ----------------------------------------------------------------------------------- chart ---

_W, _PANEL, _GAP, _LEFT, _RIGHT, _TOP = 960, 150, 46, 70, 170, 56
_INK, _MUTED, _GRID = "#1f2328", "#59636e", "#d0d7de"
_SERIES = ("#0969da", "#cf222e", "#1a7f37", "#8250df", "#bc4c00", "#57606a")


def _panel(
    y0: float,
    title: str,
    unit: str,
    t: list[float],
    series: list[tuple[str, list[float]]],
    limit: tuple[float, str] | None = None,
) -> str:
    values = [v for _, ys in series for v in ys if not math.isnan(v)]
    if limit is not None:
        values.append(limit[0])
    lo, hi = (min(values), max(values)) if values else (0.0, 1.0)
    pad = (hi - lo) * 0.08 or 1.0
    lo, hi = lo - pad, hi + pad
    t0, t1 = t[0], t[-1] if t[-1] > t[0] else t[0] + 1.0
    width = _W - _LEFT - _RIGHT

    def x(v: float) -> float:
        return _LEFT + (v - t0) / (t1 - t0) * width

    def y(v: float) -> float:
        return y0 + _PANEL - (v - lo) / (hi - lo) * _PANEL

    out = [
        f'<text x="{_LEFT}" y="{y0 - 8:.0f}" font-size="13" font-weight="600" fill="{_INK}">'
        f"{escape(title)} <tspan fill='{_MUTED}' font-weight='400'>{escape(unit)}</tspan></text>",
        f'<rect x="{_LEFT}" y="{y0}" width="{width}" height="{_PANEL}" fill="none" '
        f'stroke="{_GRID}"/>',
    ]
    for frac in (0.0, 0.5, 1.0):
        v = lo + (hi - lo) * frac
        out.append(
            f'<text x="{_LEFT - 6}" y="{y(v) + 4:.1f}" font-size="11" text-anchor="end" '
            f'fill="{_MUTED}">{v:.0f}</text>'
        )
    if limit is not None:
        out.append(
            f'<line x1="{_LEFT}" x2="{_LEFT + width}" y1="{y(limit[0]):.1f}" '
            f'y2="{y(limit[0]):.1f}" stroke="#cf222e" stroke-dasharray="6 4"/>'
            f'<text x="{_LEFT + width + 6}" y="{y(limit[0]) + 4:.1f}" font-size="11" '
            f'fill="#cf222e">{escape(limit[1])}</text>'
        )
    for i, (name, ys) in enumerate(series):
        colour = _SERIES[i % len(_SERIES)]
        pts = " ".join(f"{x(a):.1f},{y(b):.1f}" for a, b in zip(t, ys, strict=True) if b == b)
        out.append(f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="1.8"/>')
        out.append(
            f'<text x="{_LEFT + width + 6}" y="{y0 + 14 + 15 * i}" font-size="12" '
            f'fill="{colour}">{escape(name)}</text>'
        )
    return "\n".join(out)


def to_svg(design: Design, net: Network, run: Run) -> str:
    """Three panels on one time axis — flow, pump suction, coolant at the loads — with every
    state change (procedure step) marked. A picture of the trace, not a verdict."""
    tr = run.trace
    assert tr is not None
    t = tr.t
    cdus = [c.id for c in design.nodes_of("cdu")]
    pumps = [p.id for p in design.nodes_of("pump") if max(tr.series(p.id)) > netbench._FLOWING]
    loads = [n.id for n in design.nodes.values() if n.kind in LOAD_KINDS]
    flows = [(f"{c} flow", list(tr.series(c))) for c in cdus]
    npsh: list[tuple[str, list[float]]] = []
    needs: list[float] = []
    for p in pumps:
        ys = []
        for k in range(len(t)):
            j = netbench.npsh(net, tr, k, p)
            ys.append(j[0] if j is not None else math.nan)
            if j is not None:
                needs.append(j[1])
        npsh.append((f"{p} NPSHa", ys))
    hottest = [max(netbench.load_temp(net, tr, k, n)[0] for n in loads) for k in range(len(t))]
    limits = [float(v) for n in loads if (v := design.nodes[n].get("max_inlet_c")) is not None]
    supply = [(f"{c} supply", [float(v[tr.nodes.index(c)]) for v in tr.temps]) for c in cdus]
    total = _TOP + 3 * _PANEL + 2 * _GAP + 40
    width = _W - _LEFT - _RIGHT
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_W}" height="{total}" '
        f'viewBox="0 0 {_W} {total}" font-family="system-ui, sans-serif">',
        f'<rect width="{_W}" height="{total}" fill="#ffffff"/>',
        f'<text x="{_LEFT}" y="24" font-size="15" font-weight="700" fill="{_INK}">'
        f"{escape(design.project)} — {escape(run.scenario.run)}, "
        f"{escape(run.scenario.describe())}</text>",
        _panel(_TOP, "Flow through each CDU", "L/min", t, flows),
        _panel(
            _TOP + _PANEL + _GAP,
            "NPSH available at running pumps",
            "m",
            t,
            npsh,
            (max(needs), "NPSHr") if needs else None,
        ),
        _panel(
            _TOP + 2 * (_PANEL + _GAP),
            "Coolant temperature",
            "°C",
            t,
            [("hottest load", hottest), *supply],
            (min(limits), "max inlet") if limits else None,
        ),
    ]
    t0, t1 = t[0], t[-1] if t[-1] > t[0] else t[0] + 1.0
    for k0, _ in segments(tr)[1:]:
        xpos = _LEFT + (t[k0] - t0) / (t1 - t0) * width
        bottom = _TOP + 3 * _PANEL + 2 * _GAP
        parts.append(
            f'<line x1="{xpos:.1f}" x2="{xpos:.1f}" y1="{_TOP - 4}" y2="{bottom}" '
            f'stroke="{_MUTED}" stroke-dasharray="2 3"/>'
            f'<text x="{xpos + 3:.1f}" y="{bottom + 14}" font-size="11" fill="{_MUTED}" '
            f'transform="rotate(20 {xpos + 3:.1f} {bottom + 14})">'
            f"{escape(tr.label[k0].split(':')[0])}</text>"
        )
    parts.append(
        f'<text x="{_LEFT}" y="{total - 4}" font-size="10" fill="{_MUTED}">time [s] · '
        f"method: {escape(netbench.METHOD[:150])}…</text>"
    )
    parts.append("</svg>")
    return "\n".join(parts)
