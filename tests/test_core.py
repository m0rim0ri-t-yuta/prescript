"""The domain-neutral core, driven by a stub domain that shares nothing with cooling (#53).

The stub has its own design and assertion classes, its own routines and its own per-mode state,
so these tests fail if the core reaches for anything in the cooling IR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.resources import files

import pytest

from prescript.core import META_MODE, STATIC_MODE, report
from prescript.core import engine as core
from prescript.ir import META_MODE as COOLING_META
from prescript.ir import STATIC_MODE as COOLING_STATIC
from prescript.result import Result, Status, unrun


@dataclass(frozen=True)
class StubAssertion:
    id: str
    check: str
    modes: tuple[str, ...]
    severity: str = "error"


@dataclass(frozen=True)
class StubDesign:
    project: str
    modes: dict[str, float]  # mode -> a level; "blocked" has none
    assertions: tuple[StubAssertion, ...]
    limit: float = 10.0


def under_limit(design: StubDesign, level: float | None, a: StubAssertion) -> Result:
    assert level is not None, "a per-mode routine always gets its mode's state"
    if level > design.limit:
        return Result(a.id, _mode_of(design, level), Status.FAIL, "over", offending=("unit-1",))
    return Result(a.id, _mode_of(design, level), Status.PASS, "under")


def needs_rating(design: StubDesign, level: float | None, a: StubAssertion) -> Result:
    assert level is None, "the static and meta pseudo-modes have no state"
    return unrun(a.id, STATIC_MODE, "rating undecided", missing=("unit-1.rating",))


def _mode_of(design: StubDesign, level: float) -> str:
    return next(m for m, v in design.modes.items() if v == level)


REGISTRY: dict[str, core.Check[StubDesign, float]] = {
    "under_limit": under_limit,
    "needs_rating": needs_rating,
}


@dataclass
class Solver:
    """A per-mode state that can refuse a mode, and counts how often it is asked."""

    design: StubDesign
    calls: list[str] = field(default_factory=list)

    def __call__(self, mode: str) -> float:
        self.calls.append(mode)
        if mode == "blocked":
            raise core.Unsolvable("blocked: this mode has no state")
        return self.design.modes[mode]


def _design(*assertions: StubAssertion) -> StubDesign:
    return StubDesign(
        project="STUB",
        modes={"low": 4.0, "high": 12.0, "blocked": 0.0},
        assertions=assertions,
    )


def _cell(results: list[Result], aid: str, mode: str) -> Result:
    return next(r for r in results if r.assertion == aid and r.mode == mode)


def test_a_foreign_domain_gets_pass_fail_and_unrun() -> None:
    design = _design(
        StubAssertion("A-1", "under_limit", ("low", "high")),
        StubAssertion("A-2", "needs_rating", (STATIC_MODE,)),
    )
    results = core.run(design, REGISTRY, Solver(design))
    assert _cell(results, "A-1", "low").status is Status.PASS
    assert _cell(results, "A-1", "high").status is Status.FAIL
    assert _cell(results, "A-2", STATIC_MODE).status is Status.UNRUN
    assert [(r.assertion, r.mode) for r in results] == [
        ("A-1", "low"),
        ("A-1", "high"),
        ("A-2", STATIC_MODE),
    ]


def test_an_unsolvable_mode_is_unrun_with_its_reason_and_the_rest_still_runs() -> None:
    design = _design(StubAssertion("A-1", "under_limit", ("blocked", "low")))
    solver = Solver(design)
    results = core.run(design, REGISTRY, solver)
    blocked = _cell(results, "A-1", "blocked")
    assert blocked.status is Status.UNRUN
    assert blocked.detail == "blocked: this mode has no state"
    assert _cell(results, "A-1", "low").status is Status.PASS


def test_each_mode_is_solved_once_and_pseudo_modes_never() -> None:
    design = _design(
        StubAssertion("A-1", "under_limit", ("low", "blocked")),
        StubAssertion("A-2", "under_limit", ("low", "blocked")),
        StubAssertion("A-3", "needs_rating", (STATIC_MODE, META_MODE)),
    )
    solver = Solver(design)
    results = core.run(design, REGISTRY, solver)
    assert solver.calls == ["low", "blocked"]  # a refusal is remembered too
    assert _cell(results, "A-2", "blocked").status is Status.UNRUN


def test_planned_and_unknown_checks_are_unrun_never_pass() -> None:
    design = _design(
        StubAssertion("A-1", "planned_routine", ("low",)),
        StubAssertion("A-2", "typo", ("low", STATIC_MODE)),
    )
    solver = Solver(design)
    results = core.run(design, REGISTRY, solver, planned=frozenset({"planned_routine"}))
    assert _cell(results, "A-1", "low").detail == "not implemented"
    assert {r.detail for r in results if r.assertion == "A-2"} == {"unknown check 'typo'"}
    assert all(r.status is Status.UNRUN for r in results)
    assert solver.calls == []  # nothing ran, so nothing was solved


def test_an_unknown_mode_is_unrun_not_a_crash() -> None:
    design = _design(StubAssertion("A-1", "under_limit", ("nowhere",)))
    (result,) = core.run(design, REGISTRY, Solver(design))
    assert result.status is Status.UNRUN
    assert result.detail == "unknown mode 'nowhere'"


def test_a_warn_assertion_reports_warn_where_it_would_fail() -> None:
    design = _design(StubAssertion("A-1", "under_limit", ("low", "high"), severity="warn"))
    results = core.run(design, REGISTRY, Solver(design))
    assert _cell(results, "A-1", "high").status is Status.WARN
    assert _cell(results, "A-1", "low").status is Status.PASS


def test_a_post_check_runs_last_over_the_other_results() -> None:
    def count(a: StubAssertion, results: list[Result]) -> Result:
        return Result(a.id, META_MODE, Status.FAIL, f"{len(results)} cells", offending=("x",))

    design = _design(
        StubAssertion("P-1", "count", (META_MODE,), severity="warn"),
        StubAssertion("A-1", "under_limit", ("low", "high")),
    )
    results = core.run(design, REGISTRY, Solver(design), post={"count": count})
    assert results[-1].assertion == "P-1"
    assert results[-1].detail == "2 cells"
    assert results[-1].status is Status.WARN  # severity applies to post-checks too


def test_the_report_renders_a_foreign_design_with_its_own_title_and_lines() -> None:
    design = _design(
        StubAssertion("A-1", "under_limit", ("low", "high")),
        StubAssertion("A-2", "needs_rating", (STATIC_MODE,)),
    )
    results = core.run(design, REGISTRY, Solver(design))
    header, rows = report.matrix(design, results)
    assert header == ["id", "check", "low", "high", STATIC_MODE]  # unused modes are left out
    assert rows[0] == ["A-1", "under_limit", "PASS", "FAIL", ""]

    text = report.to_text(design, results, title="stub verify", extra=["note  one line"])
    assert text.startswith("stub verify — STUB\n")
    assert "PASS 1 · FAIL 1 · WARN 0 · UNRUN 1\nnote  one line\n" in text
    assert "         - unit-1.rating" in text

    md = report.to_markdown(design, results, title="Stub verify", extra=["", "_extra_"])
    assert md.startswith("### Stub verify — `STUB`")
    assert md.index("_extra_") < md.index("<details>")


def test_exit_code_fails_on_fail_and_on_unrun_only_when_strict() -> None:
    passed = [Result("A", "m", Status.PASS, "")]
    warned = [Result("A", "m", Status.WARN, "", offending=("x",))]
    open_ = [unrun("A", "m", "later")]
    failed = [Result("A", "m", Status.FAIL, "", offending=("x",))]
    assert report.exit_code(passed, strict=True) == 0
    assert report.exit_code(warned, strict=True) == 0
    assert report.exit_code(open_) == 0
    assert report.exit_code(open_, strict=True) == 1
    assert report.exit_code(failed) == 1


@pytest.mark.parametrize(
    ("core_name", "cooling_name"), [(STATIC_MODE, COOLING_STATIC), (META_MODE, COOLING_META)]
)
def test_the_cooling_pseudo_modes_are_the_cores(core_name: str, cooling_name: str) -> None:
    assert core_name == cooling_name


def test_the_package_ships_type_information() -> None:
    """Without it a domain library's mypy treats every prescript import as Any."""
    assert files("prescript").joinpath("py.typed").is_file()
