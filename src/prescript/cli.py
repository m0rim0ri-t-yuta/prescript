"""`prescript` command line: `verify`, `elaborate`, `diff`, `draw` and `sim`."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from prescript import diff as netlist_diff
from prescript import engine, modes, report
from prescript.core.report import Format, exit_code
from prescript.draw import storyboard, storyboard_html, to_svg
from prescript.ir import Design
from prescript.loader import NetlistError, load_design
from prescript.result import Status
from prescript.sim import poc
from prescript.sim import report as sim_report
from prescript.sim.uvm import Constraints, StepSequence

app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Spec-as-code for liquid cooling."
)


NetlistArg = Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="netlist.yaml")]


def _load(netlist: Path) -> Design:
    try:
        return load_design(netlist)
    except NetlistError as exc:
        typer.echo(f"netlist error: {exc}", err=True)
        raise typer.Exit(2) from exc


@app.command()
def verify(
    netlist: NetlistArg,
    fmt: Annotated[Format, typer.Option("--format", "-f")] = Format.text,
    strict: Annotated[bool, typer.Option(help="Exit 1 on UNRUN too.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run every assertion in every mode it names."""
    design = _load(netlist)
    results = engine.run(design)
    if fmt is Format.md:
        typer.echo(report.to_markdown(design, results))
    elif fmt is Format.json:
        typer.echo(report.to_json(results))
    else:
        typer.echo(report.to_text(design, results, verbose=verbose))
    raise typer.Exit(exit_code(results, strict=strict))


@app.command()
def elaborate(netlist: NetlistArg) -> None:
    """Print the elaborated IR as JSON (blocks expanded, every id unique)."""
    design = _load(netlist)
    typer.echo(design.model_dump_json(indent=2))


@app.command()
def diff(
    before: NetlistArg,
    after: NetlistArg,
    fmt: Annotated[Format, typer.Option("--format", "-f")] = Format.text,
) -> None:
    """List what changed between two netlists, after elaboration.

    It compares; it does not verify."""
    was, now = _load(before), _load(after)
    changes = netlist_diff.compare(was, now)
    if fmt is Format.md:
        typer.echo(netlist_diff.to_markdown(was, now, changes))
    elif fmt is Format.json:
        typer.echo(netlist_diff.to_json(changes))
    else:
        typer.echo(netlist_diff.to_text(was, now, changes))


@app.command()
def draw(
    netlist: NetlistArg,
    mode: Annotated[
        str | None, typer.Option("--mode", "-m", help="Draw this operating mode's states.")
    ] = None,
    procedure: Annotated[
        str | None,
        typer.Option(
            "--procedure",
            "-p",
            help="Draw every state of this procedure as a storyboard into the -o directory.",
        ),
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            "-o",
            help="Write the SVG here instead of stdout (with --procedure: a directory).",
        ),
    ] = None,
) -> None:
    """Draw the cooling loop as an SVG. It renders the netlist; it does not verify it."""
    if mode is not None and procedure is not None:
        typer.echo("--mode and --procedure are mutually exclusive", err=True)
        raise typer.Exit(2)
    design = _load(netlist)
    if procedure is not None:
        _draw_procedure(design, procedure, out)
        return
    state = None
    if mode is not None:
        if mode not in design.modes:
            known = ", ".join(design.modes) or "none"
            typer.echo(f"unknown mode: {mode} (modes in this netlist: {known})", err=True)
            raise typer.Exit(2)
        state = modes.resolve(design, design.modes[mode])
    svg = to_svg(design, state)
    if out is None:
        typer.echo(svg, nl=False)
        return
    out.write_text(svg, encoding="utf-8")
    typer.echo(f"wrote {out}", err=True)


def _draw_procedure(design: Design, name: str, out: Path | None) -> None:
    """One SVG per state of the procedure, in order, and an index.html storyboard beside them."""
    if name not in design.procedures:
        known = ", ".join(design.procedures) or "none"
        typer.echo(f"unknown procedure: {name} (procedures in this netlist: {known})", err=True)
        raise typer.Exit(2)
    if out is None:
        typer.echo("--procedure writes one SVG per step: give a directory with -o", err=True)
        raise typer.Exit(2)
    if out.exists() and not out.is_dir():
        typer.echo(f"--procedure needs -o to be a directory; {out} is a file", err=True)
        raise typer.Exit(2)
    out.mkdir(parents=True, exist_ok=True)
    frames = storyboard(design, name)
    for frame in frames:
        (out / frame.file).write_text(frame.svg, encoding="utf-8")
    (out / "index.html").write_text(storyboard_html(design, name, frames), encoding="utf-8")
    typer.echo(f"wrote {len(frames)} SVGs and {out / 'index.html'}", err=True)


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
