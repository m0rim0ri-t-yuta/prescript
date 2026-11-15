"""`prescript` command line: `verify`, `elaborate` and `sim`."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from prescript import engine, report
from prescript.loader import NetlistError, load_design
from prescript.result import Status
from prescript.sim import poc
from prescript.sim import report as sim_report
from prescript.sim.uvm import Constraints, StepSequence

app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Spec-as-code for liquid cooling."
)


class Format(StrEnum):
    text = "text"
    md = "md"
    json = "json"


NetlistArg = Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="netlist.yaml")]


@app.command()
def verify(
    netlist: NetlistArg,
    fmt: Annotated[Format, typer.Option("--format", "-f")] = Format.text,
    strict: Annotated[bool, typer.Option(help="Exit 1 on UNRUN too.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run every assertion in every mode it names."""
    try:
        design = load_design(netlist)
    except NetlistError as exc:
        typer.echo(f"netlist error: {exc}", err=True)
        raise typer.Exit(2) from exc
    results = engine.run(design)
    if fmt is Format.md:
        typer.echo(report.to_markdown(design, results))
    elif fmt is Format.json:
        typer.echo(report.to_json(results))
    else:
        typer.echo(report.to_text(design, results, verbose=verbose))
    failed = any(r.status is Status.FAIL for r in results)
    unrun = any(r.status is Status.UNRUN for r in results)
    raise typer.Exit(1 if failed or (strict and unrun) else 0)


@app.command()
def elaborate(netlist: NetlistArg) -> None:
    """Print the elaborated IR as JSON (blocks expanded, every id unique)."""
    try:
        design = load_design(netlist)
    except NetlistError as exc:
        typer.echo(f"netlist error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(design.model_dump_json(indent=2))


@app.command()
def sim(
    seed: Annotated[int, typer.Option(help="Seed for the constrained-random sequence.")] = 1,
    runs: Annotated[int, typer.Option(min=1, help="Scenarios to run.")] = 20,
    max_heat_kw: Annotated[
        float | None,
        typer.Option(help="Widen (or narrow) the heat envelope's upper bound, kW."),
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run the Phase 1 testbench (one exchanger, one PID valve) on random load steps."""
    envelope = poc.ENVELOPE
    if max_heat_kw is not None:
        try:
            envelope = Constraints(
                heat_kw=(envelope.heat_kw[0], max_heat_kw),
                facility_c=envelope.facility_c,
                step_at_s=envelope.step_at_s,
            )
        except ValueError as exc:
            typer.echo(f"sim error: {exc}", err=True)
            raise typer.Exit(2) from exc
    done = [poc.BENCH.run(item) for item in StepSequence(envelope, seed, runs)]
    typer.echo(sim_report.to_text(done, seed, envelope, verbose=verbose))
    failed = any(r.status is Status.FAIL for run in done for r in run.results)
    raise typer.Exit(1 if failed else 0)


if __name__ == "__main__":
    app()
