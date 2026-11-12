"""Keel intermediate representation (IR).

The IR is what every stage after the loader consumes. It is fully elaborated: no blocks, no
templates, every id unique. Ratings live in `attrs` with the unit in the key name
(`rating_kva`, `rating_a`, ...). A rating that the spec has not decided is `None` — never a guess.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

NodeKind = Literal[
    "source",
    "transformer",
    "bus",
    "panel",
    "ups",
    "generator",
    "ats",
    "rack_pdu",
    "load",
]
DeviceKind = Literal["breaker", "switch"]

NODE_KINDS: frozenset[str] = frozenset(NodeKind.__args__)  # type: ignore[attr-defined]
DEVICE_KINDS: frozenset[str] = frozenset(DeviceKind.__args__)  # type: ignore[attr-defined]

# Pseudo-modes: assertions that run once on the static design, or over the results themselves.
STATIC_MODE = "static"
META_MODE = "meta"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Node(_Model):
    id: str
    kind: NodeKind
    attrs: dict[str, Any] = Field(default_factory=dict)
    state: str | None = None
    provenance: str | None = None
    origin: str | None = None  # "<block>[<instance args>]" when produced by elaboration

    def get(self, key: str) -> Any:
        return self.attrs.get(key)


class Device(_Model):
    """A breaker or switch that sits on an edge."""

    id: str
    kind: DeviceKind
    attrs: dict[str, Any] = Field(default_factory=dict)
    state: Literal["closed", "open"] = "closed"
    provenance: str | None = None


class Edge(_Model):
    """Directed supply-side -> load-side connection."""

    src: str
    dst: str
    via: Device | None = None
    share: float | None = None
    bidirectional: bool = False
    role: str | None = None
    synthetic: bool = False  # created by elaboration (e.g. ATS source legs), not written by a user


class Mode(_Model):
    name: str
    overrides: dict[str, str | dict[str, str]] = Field(default_factory=dict)
    demand: dict[str, float] = Field(default_factory=dict)
    note: str | None = None


class Assertion(_Model):
    id: str
    check: str
    args: dict[str, Any] = Field(default_factory=dict)
    modes: tuple[str, ...]
    severity: Literal["error", "warn"] = "error"


class Design(_Model):
    keel: str
    project: str
    units: dict[str, str] = Field(default_factory=dict)
    nodes: dict[str, Node]
    edges: tuple[Edge, ...]
    modes: dict[str, Mode]
    assertions: tuple[Assertion, ...]

    def devices(self) -> dict[str, Device]:
        return {e.via.id: e.via for e in self.edges if e.via is not None}

    def nodes_of(self, kinds: str | list[str] | tuple[str, ...]) -> list[Node]:
        wanted = {kinds} if isinstance(kinds, str) else set(kinds)
        return [n for n in self.nodes.values() if n.kind in wanted]

    def loads_of_class(self, cls: str) -> list[Node]:
        return [n for n in self.nodes.values() if n.kind == "load" and n.get("class") == cls]

    def incoming(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.dst == node_id]
