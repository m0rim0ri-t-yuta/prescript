"""Compose the pull-request comment, bounded by what GitHub will accept.

Usage: uv run python scripts/ci_comment.py <diff-file> <report-file> <out-file> [--limit N]

`.github/workflows/prescript-verify.yml` posts one sticky comment: the change list from
`prescript diff`, then the verdict from `prescript verify`. Over the limit, the API rejects the
whole body with 422, so the verdict would be lost along with the change list -- and the job would
go red for a reason that reads nothing like "the comment was too long".

Two rules decide what gives way:

1. **The verdict is never cut while anything else can be.** It is the product's answer; the
   change list is context. So the change list loses whole lines from its end until the body fits,
   and only a report that is over the limit on its own is cut -- from the end, which keeps the
   title and the summary line.
2. **A cut is never silent.** A change list that stops early reads exactly like a design that
   changed less, and `prescript diff` states facts. Every cut leaves a note saying what was
   dropped, how much of it, and where to read it in full.

The limit is 65536 characters -- GitHub's own number, from the 422 its API returns on an
over-long body:

    {"message":"Validation Failed","errors":[{"resource":"IssueComment","code":"unprocessable",
     "field":"data","message":"Body is too long (maximum is 65536 characters)"}],"status":"422"}

It counts characters, not bytes (the reference report is 1595 characters in 1696 bytes), so this
is Python and not `wc -c`. The number is not in GitHub's REST reference; it was probed against
the API on 2026-11-16 and is worth re-probing if a comment is ever rejected again.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

# GitHub's limit on a comment body, in characters (see the module docstring).
GITHUB_COMMENT_LIMIT = 65536
# Headroom held back inside the limit: the sticky-comment action prepends its own HTML marker,
# and a body that only just fits is one that fails on the next character anyone adds.
RESERVE = 512

_LOCAL = "Run `./scripts/ci_netlist_diff.sh <base-sha> diff.md` to read it in full."
_LOG = "The full text is in this job's log, under the step that composed this comment."

Note = Callable[[int, int], str]


def _note(what: str, where: str) -> Note:
    """A note renderer: given the lines and characters cut, the sentence that admits the cut."""

    def render(lines: int, chars: int) -> str:
        return (
            f"> **{what} was cut to fit GitHub's comment limit"
            f" ({GITHUB_COMMENT_LIMIT} characters).**"
            f" {lines} more line{'' if lines == 1 else 's'} ({chars} characters)"
            f" {'is' if lines == 1 else 'are'} not shown here. {where}\n\n"
        )

    return render


def _keep_head(text: str, budget: int) -> tuple[str, int, int]:
    """Whole lines from the start of `text` that fit in `budget` characters.

    Returns the kept text and how many lines and characters were dropped. Whole lines, because
    half a Markdown table row is noise; `budget` is a hard bound, so a first line longer than it
    leaves nothing at all.
    """
    if budget <= 0:
        return "", len(text.splitlines()), len(text)
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    used = 0
    for index, line in enumerate(lines):
        if used + len(line) > budget:
            return "".join(kept), len(lines) - index, len("".join(lines[index:]))
        kept.append(line)
        used += len(line)
    return text, 0, 0


def _cut(text: str, budget: int, note: Note) -> str:
    """`text` cut to `budget` characters, note included, or unchanged when it already fits.

    The note's own length depends on the numbers in it, so the budget is reduced by the longest
    the note could ever be -- the one that admits dropping every line. That may keep one line
    fewer than strictly possible and is always inside the budget, which is the point.
    """
    reserved = budget - len(note(len(text.splitlines()), len(text)))
    kept, lines_cut, chars_cut = _keep_head(text, reserved)
    if lines_cut == 0:
        return kept
    return kept + note(lines_cut, chars_cut)


def compose(diff: str, report: str, limit: int = GITHUB_COMMENT_LIMIT) -> tuple[str, str]:
    """The comment body, and the text to echo into the job log (empty when nothing was cut).

    `limit` is the whole budget for the body; `RESERVE` is held back inside it.
    """
    budget = max(limit - RESERVE, 0)
    if len(diff) + len(report) <= budget:
        return diff + report, ""
    if len(report) > budget:
        # Pathological: the verdict alone is over the limit. The change list goes entirely.
        return _cut(report, budget, _note("The verdict", _LOG)), diff + report
    # The usual case: the report stays whole and the change list loses lines from its end. The
    # note sits between them, where the change list stops.
    note = _note("The change list", f"{_LOCAL} {_LOG}")
    kept = _cut(diff, budget - len(report), note)
    return kept + report, diff


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compose the bounded pull-request comment.")
    parser.add_argument("diff", type=Path, help="the change list, possibly empty or absent")
    parser.add_argument("report", type=Path, help="the verify report")
    parser.add_argument("out", type=Path, help="where to write the comment body")
    parser.add_argument(
        "--limit",
        type=int,
        default=GITHUB_COMMENT_LIMIT,
        help="characters the body may use (default: GitHub's %(default)s)",
    )
    args = parser.parse_args(argv)

    diff = args.diff.read_text(encoding="utf-8") if args.diff.exists() else ""
    report = args.report.read_text(encoding="utf-8") if args.report.exists() else ""
    body, dropped = compose(diff, report, args.limit)
    args.out.write_text(body, encoding="utf-8")

    if dropped:
        print(
            f"ci_comment.py: {len(diff) + len(report)} characters do not fit in {args.limit};"
            f" wrote {len(body)}. The full text follows.",
            file=sys.stderr,
        )
        print(dropped)
    else:
        print(f"ci_comment.py: wrote {len(body)} characters, inside {args.limit}.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
