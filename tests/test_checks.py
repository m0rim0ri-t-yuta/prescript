"""Each routine shows PASS, FAIL and (where reachable) UNRUN — verification-semantics.md §8."""

from __future__ import annotations

from typing import Any

import pytest

from prescript import engine
from prescript.checks.completeness import completeness
from prescript.checks.dual_path import dual_path
from prescript.checks.path_exists import path_exists
from prescript.ir import Assertion, Design
from prescript.loader import parse_design
from prescript.modes import resolve
from prescript.result import Result, Status


def _a(check: str, **args: Any) -> Assertion:
    return Assertion(id="T", check=check, args=args, modes=("normal",))


def _result(results: list[Result], aid: str, mode: str) -> Result:
    return next(r for r in results if r.assertion == aid and r.mode == mode)


# --- dual_path ------------------------------------------------------------------


def test_dual_path_pass_in_normal(design: Design) -> None:
    r = dual_path(design, resolve(design, design.modes["normal"]), _a("dual_path"))
    assert r.status is Status.PASS
    assert "RACK-08" in r.subjects


def test_dual_path_fails_when_a_rack_breaker_opens(doc: dict[str, Any]) -> None:
    doc["modes"]["normal"]["overrides"] = {"CB-DPB-03": "open"}
    d = parse_design(doc)
    r = dual_path(d, resolve(d, d.modes["normal"]), _a("dual_path"))
    assert r.status is Status.FAIL
    assert r.offending == ("RACK-03 (no live side B)",)


def test_dual_path_unrun_without_mode(design: Design) -> None:
    assert dual_path(design, None, _a("dual_path")).status is Status.UNRUN


# --- path_exists ----------------------------------------------------------------


def test_path_exists_essential_from_em_bus_in_generator(design: Design) -> None:
    s = resolve(design, design.modes["generator"])
    r = path_exists(design, s, _a("path_exists", **{"class": "essential", "from": "EM-BUS"}))
    assert r.status is Status.PASS


def test_path_exists_fails_when_em_bus_is_dead(design: Design) -> None:
    s = resolve(design, design.modes["dead-pod"])
    r = path_exists(design, s, _a("path_exists", **{"class": "essential", "from": "EM-BUS"}))
    assert r.status is Status.FAIL
    assert "CDU-01" in r.offending


def test_path_exists_unrun_for_empty_class(design: Design) -> None:
    s = resolve(design, design.modes["normal"])
    assert path_exists(design, s, _a("path_exists", **{"class": "nope"})).status is Status.UNRUN


# --- completeness: null never passes -------------------------------------------


def test_completeness_reports_null_ratings(design: Design) -> None:
    r = completeness(design, None, _a("completeness", kinds=["breaker"]))
    assert r.status is Status.FAIL
    assert "CB-HVA.rating_a" in r.offending


def test_completeness_pass_when_rated(design: Design) -> None:
    r = completeness(design, None, _a("completeness", kinds=["rack_pdu"]))
    assert r.status is Status.PASS


def test_completeness_unrun_for_unknown_kind(design: Design) -> None:
    assert completeness(design, None, _a("completeness", kinds=["x"])).status is Status.UNRUN


# --- engine-level invariants -----------------------------------------------------


def test_not_implemented_never_passes(design: Design) -> None:
    results = engine.run(design)
    a06 = [r for r in results if r.assertion == "A-06"]
    assert a06 and all(r.status is Status.UNRUN for r in a06)


def test_unknown_check_is_unrun(doc: dict[str, Any]) -> None:
    doc["assertions"].append({"id": "Z-01", "check": "made_up", "modes": ["normal"]})
    r = _result(engine.run(parse_design(doc)), "Z-01", "normal")
    assert r.status is Status.UNRUN and "unknown check" in r.detail


def test_severity_warn_downgrades_fail_only(design: Design) -> None:
    results = engine.run(design)
    assert _result(results, "A-14", "static").status is Status.WARN
    assert _result(results, "A-15", "meta").status is Status.WARN


def test_reference_design_has_no_fail(design: Design) -> None:
    results = engine.run(design)
    assert [r for r in results if r.status is Status.FAIL] == []
    assert _result(results, "A-16", "maint-A").status is Status.PASS


def test_fail_without_evidence_is_impossible() -> None:
    with pytest.raises(ValueError, match="offending"):
        Result("X", "normal", Status.FAIL, "no evidence")


def test_pass_with_missing_data_is_impossible() -> None:
    with pytest.raises(ValueError, match="missing"):
        Result("X", "normal", Status.PASS, "ok", missing=("A.rating_a",))
