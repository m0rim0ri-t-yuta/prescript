"""`keel` command line."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from keel import engine, report
from keel.loader import NetlistError, load_design
from keel.result import Status

app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Spec-as-code for power systems."
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
    """Print the elaborated IR as JSON (blocks expanded, ATS legs synthesized)."""
    try:
        design = load_design(netlist)
    except NetlistError as exc:
        typer.echo(f"netlist error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(design.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
