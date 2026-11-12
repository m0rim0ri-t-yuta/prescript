from __future__ import annotations

import re

from keel.ir import Design, Node


def side_of(node_id: str, sides: list[str]) -> str | None:
    """Return the side tag carried by an id as a whole `-X` segment (e.g. PDU-A-01 -> A)."""
    for side in sides:
        if re.search(rf"(^|-){re.escape(side)}(-|$)", node_id):
            return side
    return None


def node_side(node: Node, sides: list[str]) -> str | None:
    declared = node.get("side")
    if isinstance(declared, str) and declared in sides:
        return declared
    return side_of(node.id, sides)


def targets(design: Design, cls: str) -> list[Node]:
    return sorted(design.loads_of_class(cls), key=lambda n: n.id)
