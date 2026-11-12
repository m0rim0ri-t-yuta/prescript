"""Render results as a terminal table, Markdown (for PR comments) or JSON."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict

from prescript.ir import Design
from prescript.result import Result, Status

_ICON = {Status.PASS: "✅", Status.FAIL: "❌", Status.WARN: "⚠️", Status.UNRUN: "⏸"}


def summary(results: list[Result]) -> str:
    c = Counter(r.status for r in results)
    return " · ".join(f"{s.value} {c.get(s, 0)}" for s in Status)


def matrix(design: Design, results: list[Result]) -> tuple[list[str], list[list[str]]]:
    modes = [*design.modes, "static", "meta"]
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


def to_text(design: Design, results: list[Result], verbose: bool = False) -> str:
    header, rows = matrix(design, results)
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows, strict=False)]

    def line(cells: list[str]) -> str:
        return "  ".join(str(c).ljust(w) for c, w in zip(cells, widths, strict=False)).rstrip()

    out = [
        f"prescript verify — {design.project}",
        "",
        line(header),
        line(["-" * w for w in widths]),
    ]
    out += [line(r) for r in rows]
    out += ["", summary(results), ""]
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


def to_markdown(design: Design, results: list[Result]) -> str:
    header, rows = matrix(design, results)
    out = [f"### Prescript verify — `{design.project}`", "", f"**{summary(results)}**", ""]
    out.append("| " + " | ".join(header) + " |")
    out.append("|" + "---|" * len(header))
    for row in rows:
        cells = row[:2] + [_ICON.get(Status(c), "") if c else "" for c in row[2:]]
        out.append("| " + " | ".join(cells) + " |")
    problems = [r for r in results if r.status in (Status.FAIL, Status.WARN)]
    if problems:
        out += ["", "<details><summary>Findings</summary>", ""]
        for r in problems:
            out.append(f"- **{r.assertion}@{r.mode}** {r.status.value}: {r.detail}")
        out += ["", "</details>"]
    return "\n".join(out)


def to_json(results: list[Result]) -> str:
    return json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False)
