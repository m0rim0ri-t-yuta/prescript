"""`procedures:` (grammar v0.3): an operating procedure elaborates into ordinary modes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from prescript import engine, report
from prescript.cli import app
from prescript.ir import Assumption, Design, Procedure, Step
from prescript.loader import NetlistError, load_design, parse_design
from prescript.result import Status
from tests.conftest import REFERENCE

runner = CliRunner()

STEPS = ["stop-cdu-A@s1", "stop-cdu-A@s2", "stop-cdu-A@s3", "stop-cdu-A@s4"]


def _procedure(**over: Any) -> dict[str, Any]:
    """A one-step procedure on the reference design; keyword arguments replace its keys."""
    body: dict[str, Any] = {
        "from": "normal",
        "steps": [{"id": "s1", "action": "Stop the duty pump", "set": {"PMP-A-1": "off"}}],
    }
    body.update(over)
    return body


def _with(doc: dict[str, Any], name: str, body: dict[str, Any]) -> Design:
    doc.setdefault("procedures", {})[name] = body
    return parse_design(doc)


# ---------------------------------------------------------------- elaboration ---


def test_the_reference_procedure_reaches_the_ir(design: Design) -> None:
    proc = design.procedures["stop-cdu-A"]
    assert isinstance(proc, Procedure)
    assert proc.from_mode == "normal"
    assert proc.intent == "Planned maintenance on CDU-A; the hall runs on CDU-B throughout"
    assert proc.holds == ("C-01", "C-05", "C-06")
    assert [s.id for s in proc.steps] == ["s1", "s2", "s3", "s4"]
    assert [s.mode for s in proc.steps] == STEPS
    first = proc.steps[0]
    assert isinstance(first, Step)
    assert first.set == {"PMP-A-2": "off"}
    assert first.after_s == 30.0
    assert first.done_when == Assumption(
        assume="standby start inhibited at the controller", provenance="assumed"
    )
    assert proc.steps[2].done_when is None
    assert proc.steps[3].within_s == 60.0


def test_steps_are_cumulative_deltas(design: Design) -> None:
    assert design.modes["stop-cdu-A@s1"].overrides == {"PMP-A-2": "off"}
    assert design.modes["stop-cdu-A@s2"].overrides == {"PMP-A-2": "off", "PMP-A-1": "off"}
    assert design.modes["stop-cdu-A@s4"].overrides == {
        "PMP-A-2": "off",
        "PMP-A-1": "off",
        "CDU-A": "off",
        "V-PMP-A-1": "closed",
        "V-PMP-A-2": "closed",
    }
    assert design.modes["stop-cdu-A@s3"].note == "stop-cdu-A s3: Stop the CDU"


def test_step_modes_follow_the_hand_written_ones_in_order(design: Design) -> None:
    names = list(design.modes)
    assert names[-4:] == STEPS
    assert "@" not in "".join(names[:-4])


def test_a_step_inherits_the_from_mode(doc: dict[str, Any]) -> None:
    """Overrides, demand and conditions come from `from`; a later `set` wins over an override."""
    doc["modes"]["hot-and-shut"] = {
        "overrides": {"V-SA-01": "closed", "PMP-A-2": "on"},
        "demand": {"it_liquid": 0.8, "it_air": 1.0},
        "conditions": {"facility_supply_c": 32},
    }
    steps = [{"id": "a", "action": "Stop the standby", "set": {"PMP-A-2": "off"}}]
    design = _with(doc, "p", _procedure(**{"from": "hot-and-shut", "steps": steps}))
    mode = design.modes["p@a"]
    assert mode.overrides == {"V-SA-01": "closed", "PMP-A-2": "off"}
    assert mode.demand == {"it_liquid": 0.8, "it_air": 1.0}
    assert mode.conditions == {"facility_supply_c": 32}


def test_modes_all_includes_the_step_modes(doc: dict[str, Any]) -> None:
    doc["assertions"].append({"id": "C-99", "check": "loop_closed", "modes": "all"})
    design = parse_design(doc)
    c99 = next(a for a in design.assertions if a.id == "C-99")
    assert set(STEPS) <= set(c99.modes)


# ---------------------------------------------------------------------- holds ---


def test_holds_names_the_assertion_at_every_step(design: Design) -> None:
    by_id = {a.id: a for a in design.assertions}
    for aid in ("C-01", "C-05", "C-06"):
        assert by_id[aid].modes[-4:] == tuple(STEPS)
    assert not set(STEPS) & set(by_id["C-02"].modes)


def test_holds_does_not_duplicate_a_step_already_named(doc: dict[str, Any]) -> None:
    c01 = next(a for a in doc["assertions"] if a["id"] == "C-01")
    c01["modes"] = [*c01["modes"], "stop-cdu-A@s2"]
    design = parse_design(doc)
    modes = next(a for a in design.assertions if a.id == "C-01").modes
    assert modes.count("stop-cdu-A@s2") == 1
    assert set(STEPS) <= set(modes)


# --------------------------------------------------------------------- errors ---


@pytest.mark.parametrize(
    ("body", "match"),
    [
        (_procedure(**{"from": "no-such-mode"}), "from names unknown mode 'no-such-mode'"),
        ({"steps": _procedure()["steps"]}, "from is required"),
        (
            _procedure(steps=[{"id": "s1", "action": "x", "set": {"PMP-Z-9": "off"}}]),
            "set targets unknown id 'PMP-Z-9'",
        ),
        (
            _procedure(steps=[{"id": "s1", "action": "x", "set": {"PMP-A-1": "closed"}}]),
            "PMP-A-1 cannot be set to 'closed'",
        ),
        (
            _procedure(steps=[{"id": "s1", "action": "x", "set": {"V-PMP-A-1": "off"}}]),
            "V-PMP-A-1 cannot be set to 'off'",
        ),
        (
            _procedure(
                steps=[
                    {"id": "s1", "action": "x", "set": {"PMP-A-1": "off"}},
                    {"id": "s1", "action": "y", "set": {"CDU-A": "off"}},
                ]
            ),
            "duplicate step id 's1'",
        ),
        (_procedure(steps=[]), "steps must be a non-empty list"),
        (_procedure(steps=[{"id": "s1", "set": {"PMP-A-1": "off"}}]), "action is required"),
        (_procedure(steps=[{"id": "s1", "action": "x", "set": {}}]), "set must be a non-empty"),
        (
            _procedure(steps=[{"id": "s 1", "action": "x", "set": {"PMP-A-1": "off"}}]),
            "a step id may use only",
        ),
        (
            _procedure(
                steps=[{"id": "s1", "action": "x", "set": {"PMP-A-1": "off"}, "after_s": 0}]
            ),
            "after_s: must be a number of seconds > 0",
        ),
        (
            _procedure(
                steps=[
                    {
                        "id": "s1",
                        "action": "x",
                        "set": {"PMP-A-1": "off"},
                        "done_when": {"assume": "pump stopped"},
                    }
                ]
            ),
            "done_when: provenance is mandatory",
        ),
        (_procedure(holds=["C-404"]), "holds names unknown assertion 'C-404'"),
        (_procedure(holds=["C-13"]), "holds names assertion 'C-13', which runs on 'static'"),
        (_procedure(when="never"), "unknown keys"),
    ],
)
def test_a_malformed_procedure_is_a_netlist_error(
    doc: dict[str, Any], body: dict[str, Any], match: str
) -> None:
    with pytest.raises(NetlistError, match=match):
        _with(doc, "p", body)


def test_a_hand_written_mode_name_may_not_contain_at(doc: dict[str, Any]) -> None:
    doc["modes"]["normal@night"] = dict(doc["modes"]["normal"])
    with pytest.raises(NetlistError, match="'@' is reserved for procedure steps"):
        parse_design(doc)


def test_procedures_need_grammar_0_3(doc: dict[str, Any]) -> None:
    doc["prescript"] = 0.2
    with pytest.raises(NetlistError, match=r"procedures: needs prescript: 0\.3.*declares .*0\.2"):
        parse_design(doc)


# ------------------------------------------------------------ v0.2 unchanged ---


def test_a_v0_2_netlist_still_loads_and_reports_the_same(doc: dict[str, Any]) -> None:
    """Without `procedures:` the grammar version changes nothing in the report."""
    del doc["procedures"]
    doc["prescript"] = 0.3
    v03 = parse_design(doc)
    doc["prescript"] = 0.2
    v02 = parse_design(doc)
    assert v02.prescript == "0.2"
    assert v02.procedures == {}
    assert "@" not in "".join(v02.modes)
    text = report.to_text(v02, engine.run(v02))
    assert text == report.to_text(v03, engine.run(v03))
    assert "assumed" not in text
    assert "Assumed" not in report.to_markdown(v02, engine.run(v02))


# --------------------------------------------------------------------- verify ---


def test_the_reference_procedure_passes_and_carries_its_assumptions() -> None:
    res = runner.invoke(app, ["verify", str(REFERENCE)])
    assert res.exit_code == 0, res.output
    assert "stop-cdu-A@s4" in res.output.splitlines()[2]  # a column of the matrix
    assert (
        "assumed  stop-cdu-A@s1  standby start inhibited at the controller (provenance: assumed)"
        in res.output
    )
    md = runner.invoke(app, ["verify", "-f", "md", str(REFERENCE)]).output
    assert "- `stop-cdu-A@s2` loss of pump running feedback (provenance: assumed)" in md


def test_at_200_kw_the_exposure_opens_at_s2(tmp_path: Path) -> None:
    """PROPOSAL-BEHAVIOUR-LAYER.md §6: the duty pump stops at s2 with CDU-A still running, and
    the hall is already wholly on CDU-B — one step before the CDU stops."""
    text = REFERENCE.read_text(encoding="utf-8")
    assert text.count("heat_kw: 150,") == 9  # the block parameter and eight spec rows
    retrofit = tmp_path / "netlist.yaml"
    retrofit.write_text(text.replace("heat_kw: 150,", "heat_kw: 200,"), encoding="utf-8")

    res = runner.invoke(app, ["verify", str(retrofit)])
    assert res.exit_code == 1
    assert "FAIL   C-05@stop-cdu-A@s2: 11/26 elements over 100% of L/min rating" in res.output

    design = load_design(retrofit)
    cell = {(r.assertion, r.mode): r for r in engine.run(design)}
    assert cell["C-05", "stop-cdu-A@s1"].status is Status.PASS
    for step in STEPS[1:]:
        assert cell["C-05", step].status is Status.FAIL
        assert cell["C-06", step].status is Status.FAIL
    assert "CDU-B 2602/2300 L/min (113%)" in cell["C-05", "stop-cdu-A@s2"].offending
    assert cell["C-06", "stop-cdu-A@s2"].offending == ("CDU-B 1720/1500 kW (115%)",)
    assert cell["C-13", "static"].status is Status.PASS  # spec rows moved with the block


# ------------------------------------------------------------- elaborate/draw ---


def test_elaborate_prints_the_procedure_and_its_absolute_steps() -> None:
    res = runner.invoke(app, ["elaborate", str(REFERENCE)])
    assert res.exit_code == 0, res.output
    ir = json.loads(res.output)
    assert ir["procedures"]["stop-cdu-A"]["steps"][1]["mode"] == "stop-cdu-A@s2"
    assert ir["modes"]["stop-cdu-A@s3"]["overrides"] == {
        "PMP-A-2": "off",
        "PMP-A-1": "off",
        "CDU-A": "off",
    }


def test_draw_procedure_writes_a_storyboard(tmp_path: Path) -> None:
    out = tmp_path / "frames"
    res = runner.invoke(app, ["draw", str(REFERENCE), "--procedure", "stop-cdu-A", "-o", str(out)])
    assert res.exit_code == 0, res.output
    svgs = sorted(p.name for p in out.glob("*.svg"))
    assert svgs == [
        "stop-cdu-A-00-normal.svg",
        "stop-cdu-A-01-s1.svg",
        "stop-cdu-A-02-s2.svg",
        "stop-cdu-A-03-s3.svg",
        "stop-cdu-A-04-s4.svg",
    ]
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "<h1>Planned maintenance on CDU-A; the hall runs on CDU-B throughout</h1>" in page
    assert "s2 — Stop the duty pump" in page
    assert "assumed: loss of pump running feedback (provenance: assumed)" in page
    assert page.index("stop-cdu-A-00-normal.svg") < page.index("stop-cdu-A-04-s4.svg")
    step = (out / "stop-cdu-A-02-s2.svg").read_text(encoding="utf-8")
    assert "stop-cdu-A s2 (2/4): Stop the duty pump" in step
    assert "mode: stop-cdu-A@s2" in step


@pytest.mark.parametrize(
    "args",
    [
        ["--procedure", "stop-cdu-A", "--mode", "normal", "-o", "x"],
        ["--procedure", "stop-cdu-A"],
        ["--procedure", "no-such-procedure", "-o", "x"],
    ],
)
def test_draw_procedure_misuse_exits_two(tmp_path: Path, args: list[str]) -> None:
    args = [str(tmp_path / a) if a == "x" else a for a in args]
    res = runner.invoke(app, ["draw", str(REFERENCE), *args])
    assert res.exit_code == 2
