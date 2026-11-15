"""`prescript` command line."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from prescript import diff as netlist_diff
from prescript import engine, report
from prescript.ir import Design
from prescript.loader import NetlistError, load_design
from prescript.result import Status

app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Spec-as-code for liquid cooling."
)


class Format(StrEnum):
    text = "text"
    md = "md"
    json = "json"


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
    failed = any(r.status is Status.FAIL for r in results)
    unrun = any(r.status is Status.UNRUN for r in results)
    raise typer.Exit(1 if failed or (strict and unrun) else 0)


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


if __name__ == "__main__":
    app()
