"""loading: PASS, FAIL and UNRUN (verification-semantics.md §8)."""

from __future__ import annotations

from typing import Any

import pytest

from prescript.checks.loading import loading
from prescript.ir import Assertion, Design
from prescript.loader import parse_design
from prescript.modes import resolve
from prescript.result import Result, Status


def _run(design: Design, mode: str, **args: Any) -> Result:
    a = Assertion(id="T", check="loading", args=args, modes=(mode,))
    return loading(design, resolve(design, design.modes[mode]), a)


def _racks(doc: dict[str, Any], kw: int) -> Design:
    doc["blocks"]["rack_gb200_nvl72"]["params"]["rated_kw"] = kw
    return parse_design(doc)


def test_ups_pass_in_maint_a(design: Design) -> None:
    r = _run(design, "maint-A", kind="ups", limit=1.0, basis="kva")
    assert r.status is Status.PASS
    # 1280 kW / 0.95 = 1347 kVA on a 1500 kVA UPS.
    assert "UPS-B 90%" in r.detail
    assert "lossless radial flow" in r.detail


def test_ups_fails_after_200kw_rack_retrofit(doc: dict[str, Any]) -> None:
    d = _racks(doc, 200)
    r = _run(d, "maint-A", kind="ups", limit=1.0, basis="kva")
    assert r.status is Status.FAIL
    # (8 x 200 + 80) kW / 0.95 = 1768 kVA -> 118 %.
    assert r.offending == ("UPS-B 118% > 100% (1768/1500 kVA)",)


def test_pdu_amps_basis_continuous_limit(doc: dict[str, Any]) -> None:
    d = _racks(doc, 200)
    r = _run(d, "maint-B", kind="rack_pdu", limit=0.8, basis="amps", pf=0.95)
    # 200 kW / (sqrt(3) x 0.415 kV x 0.95) = 293 A on a 300 A PDU.
    assert r.status is Status.FAIL
    assert "PDU-A-01 98% > 80% (293/300 A)" in r.offending
    assert len(r.offending) == 8


def test_null_rating_is_unrun_not_pass(doc: dict[str, Any]) -> None:
    doc["blocks"]["ups_block"]["params"]["rating_kva"] = None
    r = _run(parse_design(doc), "normal", kind="ups", limit=1.0, basis="kva")
    assert r.status is Status.UNRUN
    assert set(r.missing) == {"UPS-A.rating_kva", "UPS-B.rating_kva"}


def test_missing_pf_is_unrun(design: Design) -> None:
    r = _run(design, "normal", kind="rack_pdu", limit=0.8, basis="amps")
    assert r.status is Status.UNRUN
    assert "PDU-A-01.pf" in r.missing


def test_missing_demand_factor_is_unrun(doc: dict[str, Any]) -> None:
    doc["modes"]["normal"]["demand"] = {"critical": 1.0}
    r = _run(parse_design(doc), "normal", kind="ups", limit=1.0, basis="kva")
    assert r.status is Status.UNRUN
    assert "mode[normal].demand.essential_duty" in r.missing


def test_fail_wins_over_missing_data(doc: dict[str, Any]) -> None:
    """An overload is reported even when other elements lack data; it is never hidden as UNRUN."""
    doc["blocks"]["rack_gb200_nvl72"]["params"]["rated_kw"] = 200
    doc["nodes"].append({"id": "BUS-X", "kind": "bus", "provenance": "assumed"})
    r = _run(parse_design(doc), "maint-A", kind=["ups", "bus"], limit=1.0, pf=0.95)
    assert r.status is Status.FAIL
    assert "BUS-X.rating_kva|rating_a" in r.missing


def test_default_basis_follows_rating_field(design: Design) -> None:
    r = _run(design, "maint-A", kind=["transformer", "panel"], limit=1.0, pf=0.95)
    assert r.status is Status.PASS


def test_unknown_basis_and_missing_limit_are_unrun(design: Design) -> None:
    assert _run(design, "normal", kind="ups", limit=1.0, basis="watts").status is Status.UNRUN
    assert _run(design, "normal", kind="ups").status is Status.UNRUN


def test_static_mode_is_unrun(design: Design) -> None:
    a = Assertion(id="T", check="loading", args={"kind": "ups", "limit": 1.0}, modes=("static",))
    assert loading(design, None, a).status is Status.UNRUN


@pytest.mark.parametrize("mode", ["normal", "maint-A", "maint-B", "generator", "tie-closed"])
def test_reference_design_loading_passes(design: Design, mode: str) -> None:
    r = _run(design, mode, kind="rack_pdu", limit=0.8, basis="amps", pf=0.95)
    assert r.status is Status.PASS
