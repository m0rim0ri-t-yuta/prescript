"""Compare two elaborated netlists and say what actually changed.

`git diff` shows the text. One edited block parameter is one text line, and eight racks move
behind it. This module compares the IR after elaboration, so the change list is the change: every
node, edge, valve, mode, assertion and fluid that differs, by id, in a deterministic order.

It reports facts, not verdicts. Whether a change makes an assertion fail is `prescript verify`'s
answer, never this one's.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from prescript.ir import Design

ADDED = "added"
REMOVED = "removed"
CHANGED = "changed"

_SIGN = {ADDED: "+", REMOVED: "-", CHANGED: "~"}


@dataclass(frozen=True)
class Change:
    """One difference. `field` is empty when the whole element was added or removed."""

    what: str  # node | edge | mode | assertion | fluid | spec | design
    subject: str
    how: str
    field: str = ""
    before: Any = None
    after: Any = None
    origin: str | None = None  # the block instance a node came from, for grouping


def _fmt(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_fmt(v) for v in value) + "]"
    return str(value)


def _block_of(origin: str | None) -> str | None:
    """`rack_gb200_nvl72[n=01]` -> `rack_gb200_nvl72`; a hand-written node has no block."""
    return origin.split("[", 1)[0] if origin else None


def _fields(
    what: str,
    subject: str,
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    prefix: str = "",
    origin: str | None = None,
) -> list[Change]:
    """Per-key changes between two attribute maps, in key order."""
    out: list[Change] = []
    for key in sorted(set(before) | set(after)):
        was, now = before.get(key), after.get(key)
        if was == now:
            continue
        out.append(Change(what, subject, CHANGED, f"{prefix}{key}", was, now, origin))
    return out


def _edge_key(design: Design) -> dict[str, dict[str, Any]]:
    """Every edge as `src → dst [via]` -> the values worth comparing."""
    out: dict[str, dict[str, Any]] = {}
    for edge in design.edges:
        label = f"{edge.src} → {edge.dst}"
        if edge.via is not None:
            label += f" via {edge.via.id}"
        body: dict[str, Any] = {
            "share": edge.share,
            "bidirectional": edge.bidirectional,
            "role": edge.role,
        }
        if edge.via is not None:
            body["valve.state"] = edge.via.state
            body.update({f"valve.{k}": v for k, v in edge.via.attrs.items()})
        out[label] = body
    return out


def _elements(
    what: str,
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
    origins: dict[str, str | None] | None = None,
) -> list[Change]:
    out: list[Change] = []
    for key in sorted(set(before) | set(after)):
        origin = (origins or {}).get(key)
        if key not in after:
            out.append(Change(what, key, REMOVED, before=before[key], origin=origin))
        elif key not in before:
            out.append(Change(what, key, ADDED, after=after[key], origin=origin))
        else:
            out += _fields(what, key, before[key], after[key], origin=origin)
    return out


def compare(before: Design, after: Design) -> list[Change]:
    """Every difference between two elaborated designs, deepest detail first within an element."""
    changes: list[Change] = []

    changes += _fields(
        "design",
        "design",
        {"project": before.project, "grammar": before.prescript, **before.units},
        {"project": after.project, "grammar": after.prescript, **after.units},
    )

    changes += _elements(
        "fluid",
        {n: f.model_dump(exclude={"name"}) for n, f in before.fluids.items()},
        {n: f.model_dump(exclude={"name"}) for n, f in after.fluids.items()},
    )

    changes += _elements(
        "node",
        {i: {"kind": n.kind, "state": n.state, **n.attrs} for i, n in before.nodes.items()},
        {i: {"kind": n.kind, "state": n.state, **n.attrs} for i, n in after.nodes.items()},
        {i: n.origin for i, n in {**before.nodes, **after.nodes}.items()},
    )

    changes += _elements("edge", _edge_key(before), _edge_key(after))

    changes += _elements(
        "mode",
        {
            n: {
                **{f"overrides.{k}": v for k, v in m.overrides.items()},
                **{f"demand.{k}": v for k, v in m.demand.items()},
                **{f"conditions.{k}": v for k, v in m.conditions.items()},
                "note": m.note,
            }
            for n, m in before.modes.items()
        },
        {
            n: {
                **{f"overrides.{k}": v for k, v in m.overrides.items()},
                **{f"demand.{k}": v for k, v in m.demand.items()},
                **{f"conditions.{k}": v for k, v in m.conditions.items()},
                "note": m.note,
            }
            for n, m in after.modes.items()
        },
    )

    changes += _elements(
        "assertion",
        {
            a.id: {"check": a.check, "modes": a.modes, "severity": a.severity, **a.args}
            for a in before.assertions
        },
        {
            a.id: {"check": a.check, "modes": a.modes, "severity": a.severity, **a.args}
            for a in after.assertions
        },
    )

    return changes


# ------------------------------------------------------------------- rendering ---


@dataclass(frozen=True)
class Group:
    """Changes that say the same thing about elements of one block, collapsed into one line."""

    how: str
    label: str
    detail: str
    members: tuple[str, ...]


def group(changes: list[Change]) -> list[Group]:
    """Collapse an identical change across one block's elements; everything else stands alone."""
    buckets: dict[tuple[Any, ...], list[Change]] = {}
    order: list[tuple[Any, ...]] = []
    for c in changes:
        block = _block_of(c.origin)
        if not block:
            key: tuple[Any, ...] = ("alone", id(c))
        elif c.how == CHANGED:
            # The same edit to several elements of one block is one decision, so one line.
            key = (c.what, c.how, c.field, _fmt(c.before), _fmt(c.after), block)
        else:
            key = (c.what, c.how, block)  # a whole block instance arriving or leaving
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(c)

    groups: list[Group] = []
    for key in order:
        members = buckets[key]
        first = members[0]
        if first.how == CHANGED:
            detail = f"{first.field}: {_fmt(first.before)} → {_fmt(first.after)}"
        else:
            body = first.after if first.how == ADDED else first.before
            kind = body.get("kind") if isinstance(body, dict) else None
            detail = f"({kind})" if kind and len(members) == 1 else ""
        if len(members) == 1:
            label = f"{first.what} {first.subject}"
        else:
            label = f"{_block_of(first.origin)} x{len(members)}"
        groups.append(Group(first.how, label, detail, tuple(m.subject for m in members)))
    return groups


def _members(members: tuple[str, ...]) -> str:
    if len(members) == 1:
        return ""
    if len(members) == 2:
        return f"({members[0]}, {members[1]})"
    return f"({members[0]} … {members[-1]})"


def summary(changes: list[Change]) -> str:
    if not changes:
        return "no changes"
    counted = {how: sum(1 for c in changes if c.how == how) for how in (ADDED, REMOVED, CHANGED)}
    parts = [f"{n} {how}" for how, n in counted.items() if n]
    if len(parts) == 1:
        return f"{len(changes)} {parts[0].split(' ', 1)[1]}"
    return f"{len(changes)} changes — " + ", ".join(parts)


def _title(before: Design, after: Design) -> str:
    if before.project == after.project:
        return before.project
    return f"{before.project} → {after.project}"


def to_text(before: Design, after: Design, changes: list[Change]) -> str:
    out = [f"prescript diff — {_title(before, after)}", ""]
    rows = [(_SIGN[g.how], g.label, g.detail, _members(g.members)) for g in group(changes)]
    if rows:
        widths = [max(len(r[i]) for r in rows) for i in range(3)]
        out += [
            f"{s}  {label.ljust(widths[1])}  {detail.ljust(widths[2])}  {members}".rstrip()
            for s, label, detail, members in rows
        ]
        out.append("")
    out += [summary(changes), ""]
    out.append("A change list, not a verdict — run `prescript verify` for pass/fail.")
    return "\n".join(out)


def to_markdown(before: Design, after: Design, changes: list[Change]) -> str:
    out = [
        f"### Prescript diff — `{_title(before, after)}`",
        "",
        f"**{summary(changes)}**",
    ]
    groups = group(changes)
    if groups:
        out += ["", "| | what | change | elements |", "|---|---|---|---|"]
        for g in groups:
            members = ", ".join(g.members) if len(g.members) > 1 else ""
            out.append(f"| `{_SIGN[g.how]}` | `{g.label}` | {g.detail} | {members} |")
    out += ["", "A change list, not a verdict — run `prescript verify` for pass/fail."]
    return "\n".join(out)


def to_json(changes: list[Change]) -> str:
    return json.dumps([asdict(c) for c in changes], indent=2, ensure_ascii=False, default=str)
