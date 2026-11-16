"""Render cooling results as a terminal table, Markdown (for PR comments) or JSON.

The rendering is the core's (`prescript.core.report`); this module adds what only the cooling
domain has, the `done_when` assumptions of its procedures.
"""

from __future__ import annotations

from prescript.core import report as core
from prescript.core.report import matrix, summary, to_json
from prescript.ir import Design
from prescript.result import Result

__all__ = ["assumptions", "matrix", "summary", "to_json", "to_markdown", "to_text"]


def assumptions(design: Design) -> list[tuple[str, str, str]]:
    """Every procedure step's `done_when`, as (step mode, assumption, provenance), in order.

    They are stated preconditions, never evaluated: the report carries them so that a step's
    PASS is never read as proof that the plant got there."""
    return [
        (step.mode, step.done_when.assume, step.done_when.provenance)
        for procedure in design.procedures.values()
        for step in procedure.steps
        if step.done_when is not None
    ]


def to_text(design: Design, results: list[Result], verbose: bool = False) -> str:
    assumed = assumptions(design)
    mode_w = max((len(mode) for mode, _, _ in assumed), default=0)
    extra = [
        f"assumed  {mode.ljust(mode_w)}  {assume} (provenance: {provenance})"
        for mode, assume, provenance in assumed
    ]
    return core.to_text(design, results, title="prescript verify", verbose=verbose, extra=extra)


def to_markdown(design: Design, results: list[Result]) -> str:
    assumed = assumptions(design)
    extra: list[str] = []
    if assumed:
        extra += [
            "",
            "**Assumed, not proven** (`done_when` of procedure steps; never evaluated):",
            "",
        ]
        extra += [
            f"- `{mode}` {assume} (provenance: {provenance})"
            for mode, assume, provenance in assumed
        ]
    return core.to_markdown(design, results, title="Prescript verify", extra=extra)
