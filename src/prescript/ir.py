"""Prescript intermediate representation (IR).

The IR is what every stage after the loader consumes. It is fully elaborated: no blocks, no
templates, every id unique. Ratings live in `attrs` with the unit in the key name
(`rating_lpm`, `rating_kw`, ...). A rating that the spec has not decided is `None` — never a guess.

The domain is the technology cooling loop (TCS) of single-phase direct liquid cooling: a CDU
drives a glycol mix through headers, manifolds and cold plates and back. The facility water loop
on the other side of the CDU exchanger is a boundary condition, carried as a mode `condition`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

NodeKind = Literal[
    "cdu",  # coolant distribution unit: liquid-to-liquid exchanger, pump set, control
    "pump",  # one pump of a set; N+1 redundancy is modelled as parallel pumps
    "header",  # supply or return main
    "manifold",  # row or rack manifold
    "rack",  # liquid-cooled IT rack (cold plates lumped at rack level in v0.2)
    "rdhx",  # rear-door exchanger: the hall's residual air-cooled load, on the same loop
]
DeviceKind = Literal["valve", "check_valve"]

NODE_KINDS: frozenset[str] = frozenset(NodeKind.__args__)  # type: ignore[attr-defined]
DEVICE_KINDS: frozenset[str] = frozenset(DeviceKind.__args__)  # type: ignore[attr-defined]

# Where heat enters the loop. A flow path ends at a load; accumulation never walks through one.
LOAD_KINDS: frozenset[str] = frozenset({"rack", "rdhx"})
# What drives circulation, and where a loop is cut when flow is accumulated around it.
SOURCE_KINDS: frozenset[str] = frozenset({"cdu"})

# Pseudo-modes: assertions that run once on the static design, or over the results themselves.
STATIC_MODE = "static"
META_MODE = "meta"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Fluid(_Model):
    """Properties of a named fluid at loop temperature. `None` where the spec has not decided."""

    name: str
    cp_kj_kgk: float | None = None
    density_kg_l: float | None = None
    viscosity_mpas: float | None = None  # dynamic viscosity; only pressure drop needs it
    provenance: str | None = None

    def volumetric_heat_kj_lk(self) -> float | None:
        """kJ per litre per kelvin — the `rho * cp` of Q = V * rho * cp * dT."""
        if self.cp_kj_kgk is None or self.density_kg_l is None:
            return None
        return self.cp_kj_kgk * self.density_kg_l


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
    """A valve that sits on an edge. `open` conducts; `closed` does not."""

    id: str
    kind: DeviceKind
    attrs: dict[str, Any] = Field(default_factory=dict)
    state: Literal["open", "closed"] = "open"
    provenance: str | None = None


class Edge(_Model):
    """Directed supply-side -> load-side connection, i.e. the direction cooling travels."""

    src: str
    dst: str
    via: Device | None = None
    share: float | None = None
    bidirectional: bool = False
    role: str | None = None
    origin: str | None = None  # "<block>[<instance args>]" when produced by elaboration


class SpecTable(_Model):
    """A sheet of the spec this design was taken from, transcribed: one row per element id.

    The IR carries it so that `consistency` stays a pure function — reading files is the loader's
    job. A cell the spec has not decided is `None`, exactly like a rating.
    """

    name: str
    rows: dict[str, dict[str, Any]] = Field(default_factory=dict)
    provenance: str | None = None


class Mode(_Model):
    name: str
    overrides: dict[str, str] = Field(default_factory=dict)
    demand: dict[str, float] = Field(default_factory=dict)
    conditions: dict[str, float] = Field(default_factory=dict)
    note: str | None = None


class Assertion(_Model):
    id: str
    check: str
    args: dict[str, Any] = Field(default_factory=dict)
    modes: tuple[str, ...]
    severity: Literal["error", "warn"] = "error"


class Design(_Model):
    prescript: str
    project: str
    units: dict[str, str] = Field(default_factory=dict)
    fluids: dict[str, Fluid] = Field(default_factory=dict)
    spec: dict[str, SpecTable] = Field(default_factory=dict)
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
        return [n for n in self.nodes.values() if n.kind in LOAD_KINDS and n.get("class") == cls]

    def incoming(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.dst == node_id]

    def outgoing(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.src == node_id]

    def fluid_of(self, node: Node) -> Fluid | None:
        name = node.get("fluid")
        return self.fluids.get(str(name)) if name is not None else None
