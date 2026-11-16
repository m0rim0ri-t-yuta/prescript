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


SETTINGS = Path(__file__).resolve().parent.parent / ".claude" / "settings.json"


def test_settings_registers_the_hook() -> None:
    """The regexes above only run if the hook is wired in. Nothing else checks that."""
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for entry in settings["hooks"]["PreToolUse"]
        if entry["matcher"] == "Bash"
        for hook in entry["hooks"]
    ]
    assert any("agent_hooks/block_unsafe_git.py" in c for c in commands)


def test_registration_only_binds_this_project_dir() -> None:
    """Documented in agent-config/rules/safety.md: the guard is scoped, so the rule is the gate."""
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "$CLAUDE_PROJECT_DIR" in command
