"""`diff` compares two elaborated netlists: facts about what changed, never a verdict."""

from __future__ import annotations

import json
from typing import Any

from typer.testing import CliRunner

from prescript import diff
from prescript.cli import app
from prescript.ir import Design
from prescript.loader import parse_design
from tests.conftest import REFERENCE

runner = CliRunner()

SPARE_RDHX = {
    "id": "RDHX-02",
    "kind": "rdhx",
    "class": "it_air",
    "heat_kw": 60,
    "delta_t_k": 10,
    "max_inlet_c": 40,
    "dp_kpa": 50,
    "dp_lpm": 90,
    "fluid": "pg25",
    "provenance": "assumed: a second rear door, for the test",
}


def test_a_design_does_not_differ_from_itself(design: Design) -> None:
    assert diff.compare(design, design) == []
    assert "no changes" in diff.to_text(design, design, [])


def test_one_block_parameter_is_one_line_for_eight_racks(
    doc: dict[str, Any], design: Design
) -> None:
    """Diffing the IR is the point: `git diff` shows one edited line, this shows eight racks."""
    doc["blocks"]["rack_gb200_nvl72"]["params"]["heat_kw"] = 200
    changes = diff.compare(design, parse_design(doc))
    assert len(changes) == 8
    assert all(c.what == "node" and c.field == "heat_kw" for c in changes)
    groups = diff.group(changes)
    assert len(groups) == 1
    assert groups[0].label == "rack_gb200_nvl72 x8"
    assert groups[0].detail == "heat_kw: 150 → 200"
    assert groups[0].members[0] == "RACK-01" and groups[0].members[-1] == "RACK-08"


def test_an_added_node_is_added_and_removed_the_other_way_round(
    doc: dict[str, Any], design: Design
) -> None:
    doc["nodes"].append(SPARE_RDHX)
    grown = parse_design(doc)
    added = diff.compare(design, grown)
    assert [(c.what, c.subject, c.how) for c in added] == [("node", "RDHX-02", diff.ADDED)]
    removed = diff.compare(grown, design)
    assert [(c.what, c.subject, c.how) for c in removed] == [("node", "RDHX-02", diff.REMOVED)]
    assert diff.group(added)[0].detail == "(rdhx)"


def test_an_edge_and_its_valve_are_compared(doc: dict[str, Any], design: Design) -> None:
    doc["blocks"]["rack_gb200_nvl72"]["params"]["branch_kv"] = 90
    changes = diff.compare(design, parse_design(doc))
    assert changes and all(c.what == "edge" and c.field == "valve.kv_m3h" for c in changes)
    assert changes[0].before == 60 and changes[0].after == 90


def test_modes_assertions_and_fluids_are_compared(doc: dict[str, Any], design: Design) -> None:
    doc["modes"]["summer-peak"]["conditions"]["facility_supply_c"] = 35
    doc["assertions"][9]["args"]["tolerance_pct"] = 5  # C-10 balance
    doc["fluids"]["pg25"]["cp_kj_kgk"] = 3.9
    changes = {
        (c.what, c.subject, c.field): (c.before, c.after)
        for c in diff.compare(design, parse_design(doc))
    }
    assert changes[("mode", "summer-peak", "conditions.facility_supply_c")] == (32, 35)
    assert changes[("assertion", "C-10", "tolerance_pct")] == (10, 5)
    assert changes[("fluid", "pg25", "cp_kj_kgk")] == (3.85, 3.9)


def test_the_project_name_and_grammar_are_compared(doc: dict[str, Any], design: Design) -> None:
    doc["project"] = "GB200-2SU"
    changes = diff.compare(design, parse_design(doc))
    assert [(c.what, c.field, c.after) for c in changes] == [("design", "project", "GB200-2SU")]


def test_the_same_pair_renders_the_same_bytes(doc: dict[str, Any], design: Design) -> None:
    doc["blocks"]["rack_gb200_nvl72"]["params"]["heat_kw"] = 200
    grown = parse_design(doc)
    first = diff.to_text(design, grown, diff.compare(design, grown))
    assert first == diff.to_text(design, grown, diff.compare(design, grown))


def test_json_names_every_change(doc: dict[str, Any], design: Design) -> None:
    doc["nodes"].append(SPARE_RDHX)
    rows = json.loads(diff.to_json(diff.compare(design, parse_design(doc))))
    assert rows[0]["what"] == "node" and rows[0]["how"] == "added"
    assert rows[0]["subject"] == "RDHX-02"


def test_markdown_is_a_table_for_a_pr_comment(doc: dict[str, Any], design: Design) -> None:
    doc["blocks"]["rack_gb200_nvl72"]["params"]["heat_kw"] = 200
    md = diff.to_markdown(design, parse_design(doc), diff.compare(design, parse_design(doc)))
    assert md.startswith("### Prescript diff — `GB200-1SU-DLC-POC`")
    assert "| `~` | `rack_gb200_nvl72 x8` | heat_kw: 150 → 200 |" in md
    assert "not a verdict" in md


def test_cli_diffs_two_files() -> None:
    res = runner.invoke(app, ["diff", str(REFERENCE), str(REFERENCE)])
    assert res.exit_code == 0, res.output
    assert "no changes" in res.output


def test_cli_rejects_a_broken_netlist(tmp_path: Any) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("prescript: 9.9\n", encoding="utf-8")
    assert runner.invoke(app, ["diff", str(REFERENCE), str(bad)]).exit_code == 2
