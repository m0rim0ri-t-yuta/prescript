"""Check results. The status set is closed (agent-config/rules/verification-semantics.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    UNRUN = "UNRUN"


@dataclass(frozen=True)
class Result:
    assertion: str
    mode: str
    status: Status
    detail: str
    subjects: tuple[str, ...] = ()
    offending: tuple[str, ...] = ()
    missing: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.status is Status.FAIL and not self.offending:
            raise ValueError(f"{self.assertion}/{self.mode}: a FAIL must name offending elements")
        if self.status is Status.PASS and self.missing:
            raise ValueError(f"{self.assertion}/{self.mode}: PASS with missing data is forbidden")


def unrun(assertion: str, mode: str, detail: str, missing: tuple[str, ...] = ()) -> Result:
    return Result(assertion, mode, Status.UNRUN, detail, missing=missing)
