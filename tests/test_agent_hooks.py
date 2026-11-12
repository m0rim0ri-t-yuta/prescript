from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "scripts" / "agent_hooks" / "block_unsafe_git.py"


def _run(command: str) -> int:
    payload = json.dumps({"tool_input": {"command": command}})
    return subprocess.run(
        [sys.executable, str(HOOK)], input=payload, text=True, capture_output=True
    ).returncode


@pytest.mark.parametrize(
    "cmd",
    [
        "git commit --no-verify -m x",
        "git commit -nm x",
        "git push --force origin feature/1-x",
        "git push -f",
        "git push origin +feature/1-x",
        "git push origin main",
        "gh pr merge 3 --squash",
    ],
)
def test_blocks_gate_bypass(cmd: str) -> None:
    assert _run(cmd) == 2


@pytest.mark.parametrize(
    "cmd",
    ["git push -u origin feature/1-x", "git commit -m 'feat: x'", "gh pr create --fill"],
)
def test_allows_normal_flow(cmd: str) -> None:
    assert _run(cmd) == 0
