"""Claude Code PreToolUse hook: deny git commands that bypass gates.

Reads the hook JSON on stdin. Exit 2 blocks the tool call and shows stderr to the agent.
"""

from __future__ import annotations

import json
import re
import sys

RULES: list[tuple[str, str]] = [
    (r"--no-verify\b", "--no-verify skips the pre-commit/pre-push gates"),
    (
        r"\bgit\s+commit\b[^|;&\"']*\s-[a-zA-Z]*n[a-zA-Z]*\b",
        "git commit -n skips the pre-commit gate",
    ),
    (r"\bgit\s+push\b[^|;&]*\s(--force\b|--force-with-lease\b|-f\b)", "force-push"),
    (r"\bgit\s+push\b[^|;&]*\s\+\S+", "force-push via +refspec"),
    (r"\bgit\s+push\b[^|;&]*\s(--delete\s+main\b|:main\b)", "deleting main"),
    (r"\bgit\s+push\b[^|;&]*\sorigin\s+(HEAD:)?main\b", "pushing to main (open a PR)"),
    (r"\bgh\s+pr\s+merge\b", "agents never merge (review-governance.md)"),
]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("block_unsafe_git: unreadable hook input (fail-closed)", file=sys.stderr)
        return 2
    command = str(payload.get("tool_input", {}).get("command", ""))
    for pattern, reason in RULES:
        if re.search(pattern, command):
            print(f"Blocked: {reason}. See agent-config/rules/safety.md.", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
