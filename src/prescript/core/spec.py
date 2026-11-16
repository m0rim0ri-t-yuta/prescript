"""What the core reads from a domain's design, and nothing more.

Protocols, not base classes: a domain's pydantic models satisfy them by having the attributes, so
a domain library depends on prescript without inheriting from it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

# Pseudo-modes. An assertion in `static` checks the design as written; one in `meta` checks the
# design (or the other results) as a whole. Neither has a per-mode state.
STATIC_MODE = "static"
META_MODE = "meta"


class AssertionSpec(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def check(self) -> str: ...

    @property
    def modes(self) -> Sequence[str]: ...

    @property
    def severity(self) -> str: ...  # "error" or "warn"; only "warn" changes anything


class DesignSpec(Protocol):
    @property
    def project(self) -> str: ...

    @property
    def modes(self) -> Mapping[str, object]: ...

    @property
    def assertions(self) -> Sequence[AssertionSpec]: ...
