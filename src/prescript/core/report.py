"""Render results as a terminal table, Markdown (for PR comments) or JSON, and the exit code.

A domain adds its own lines with `extra` (cooling adds the `done_when` assumptions of its
procedures); the matrix, the summary, the UNRUN grouping and the findings are the same for every
domain.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from enum import StrEnum

from prescript.core.spec import META_MODE, STATIC_MODE, DesignSpec
from prescript.result import Result, Status

_ICON = {Status.PASS: "✅", Status.FAIL: "❌", Status.WARN: "⚠️", Status.UNRUN: "⏸"}


class Format(StrEnum):
    text = "text"
    md = "md"
    json = "json"


def summary(results: list[Result]) -> str:
    c = Counter(r.status for r in results)
    return " · ".join(f"{s.value} {c.get(s, 0)}" for s in Status)


def matrix(design: DesignSpec, results: list[Result]) -> tuple[list[str], list[list[str]]]:
    modes = [*design.modes, STATIC_MODE, META_MODE]
    used = [m for m in modes if any(r.mode == m for r in results)]
    by_cell = {(r.assertion, r.mode): r for r in results}
    rows = []
    for a in design.assertions:
        row = [a.id, a.check]
        for m in used:
            r = by_cell.get((a.id, m))
            row.append(r.status.value if r else "")
        rows.append(row)
    return ["id", "check", *used], rows


def to_text(
    design: DesignSpec,
    results: list[Result],
    *,
    title: str,
    verbose: bool = False,
    extra: Sequence[str] = (),
) -> str:
    """`title` heads the table (`prescript verify`); `extra` lines follow the summary."""
    header, rows = matrix(design, results)
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows, strict=False)]

    def line(cells: list[str]) -> str:
        return "  ".join(str(c).ljust(w) for c, w in zip(cells, widths, strict=False)).rstrip()

    out = [
        f"{title} — {design.project}",
        "",
        line(header),
        line(["-" * w for w in widths]),
    ]
    out += [line(r) for r in rows]
    out += ["", summary(results), *extra, ""]
    # UNRUN cells of one assertion usually share a reason: print them once.
    unrun_groups: dict[tuple[str, str], list[str]] = {}
    for r in results:
        if r.status is Status.UNRUN and not r.missing:
            unrun_groups.setdefault((r.assertion, r.detail), []).append(r.mode)
    for (aid, detail), modes in unrun_groups.items():
        out.append(f"UNRUN  {aid}@{','.join(modes)}: {detail}")
    for r in results:
        if r.status is Status.PASS and not verbose:
            continue
        if r.status is Status.UNRUN and not r.missing:
            continue
        out.append(f"{r.status.value:5}  {r.assertion}@{r.mode}: {r.detail}")
        for item in (r.offending or r.missing)[: None if verbose else 6]:
            out.append(f"         - {item}")
        hidden = len(r.offending or r.missing) - 6
        if hidden > 0 and not verbose:
            out.append(f"         … {hidden} more (use --verbose)")
    return "\n".join(out)


def to_markdown(
    design: DesignSpec,
    results: list[Result],
    *,
    title: str,
    extra: Sequence[str] = (),
) -> str:
    """`title` heads the comment (`Prescript verify`); `extra` lines follow the matrix."""
    header, rows = matrix(design, results)
    out = [f"### {title} — `{design.project}`", "", f"**{summary(results)}**", ""]
    out.append("| " + " | ".join(header) + " |")
    out.append("|" + "---|" * len(header))
    for row in rows:
        cells = row[:2] + [_ICON.get(Status(c), "") if c else "" for c in row[2:]]
        out.append("| " + " | ".join(cells) + " |")
    out += extra
    problems = [r for r in results if r.status in (Status.FAIL, Status.WARN)]
    if problems:
        out += ["", "<details><summary>Findings</summary>", ""]
        for r in problems:
            out.append(f"- **{r.assertion}@{r.mode}** {r.status.value}: {r.detail}")
        out += ["", "</details>"]
    return "\n".join(out)


def to_json(results: list[Result]) -> str:
    return json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False)


def exit_code(results: list[Result], *, strict: bool = False) -> int:
    """1 on any FAIL, and with `strict` on any UNRUN too; else 0. WARN never fails a run."""
    failed = any(r.status is Status.FAIL for r in results)
    unrun = any(r.status is Status.UNRUN for r in results)
    return 1 if failed or (strict and unrun) else 0
