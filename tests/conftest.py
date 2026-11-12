from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from keel.ir import Design
from keel.loader import _Yaml12BoolLoader, parse_design

REFERENCE = Path(__file__).resolve().parent.parent / "examples" / "gb200-1su" / "netlist.yaml"


@pytest.fixture(scope="session")
def reference_doc() -> dict[str, Any]:
    with open(REFERENCE, encoding="utf-8") as fh:
        doc: dict[str, Any] = yaml.load(fh, Loader=_Yaml12BoolLoader)
    return doc


@pytest.fixture
def doc(reference_doc: dict[str, Any]) -> dict[str, Any]:
    """A mutable copy of the reference netlist for one test."""
    return copy.deepcopy(reference_doc)


@pytest.fixture
def design(doc: dict[str, Any]) -> Design:
    return parse_design(doc)
