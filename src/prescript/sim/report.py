"""Render a regression of testbench runs as text, in the shape `prescript verify` uses."""

from __future__ import annotations

from prescript import report
from prescript.result import Status
from prescript.sim import plant
from prescript.sim.uvm import Constraints, Run


def to_text(runs: list[Run], seed: int, envelope: Constraints, verbose: bool = False) -> str:
    results = [r for run in runs for r in run.results]
    heat, water, step = envelope.heat_kw, envelope.facility_c, envelope.step_at_s
    out = [
        f"prescript sim — Phase 1 testbench, seed {seed}, {len(runs)} runs",
        f"envelope: heat {heat[0]:.0f}-{heat[1]:.0f} kW, facility water "
        f"{water[0]:.1f}-{water[1]:.1f} °C, step at t={step[0]}-{step[1]} s",
        f"method: {plant.METHOD}",
        "",
        "run     S-01   S-02   scenario",
    ]
    for run in runs:
        by_id = {r.assertion: r.status.value for r in run.results}
        scenario = run.item.describe().split(": ", 1)[1]
        out.append(f"{run.item.run}  {by_id['S-01']:5}  {by_id['S-02']:5}  {scenario}")
    out += ["", report.summary(results)]
    shown = [r for r in results if verbose or r.status is not Status.PASS]
    if shown:
        out.append("")
    for r in shown:
        detail = r.detail.split("; method: ", 1)[0]
        out.append(f"{r.status.value:5}  {r.assertion}@{r.mode}: {detail}")
        out += [f"         - {item}" for item in r.offending]
    return "\n".join(out)
