"""Generate Claude adapters from the agent-config SSOT.

    uv run python scripts/sync_agent_config.py          # write adapters
    uv run python scripts/sync_agent_config.py --check  # exit 1 on drift (CI / pre-push)

SSOT -> adapter:
    agent-config/claude-md.template -> CLAUDE.md
    agent-config/rules/*.md         -> .claude/rules/*.md
    agent-config/agents/*.md        -> .claude/agents/*.md
    .agents/skills/<name>/**        -> .claude/skills/<name>/**
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADER = "<!-- GENERATED from {src} by scripts/sync_agent_config.py. Edit the source. -->\n"


def _with_header(src: Path, text: str) -> str:
    header = HEADER.format(src=src.relative_to(ROOT).as_posix())
    if text.startswith("---\n"):
        # Keep YAML frontmatter first so Claude Code still parses it.
        end = text.index("\n---\n", 4) + len("\n---\n")
        return text[:end] + "\n" + header + text[end:]
    return header + "\n" + text


def expected_files() -> dict[Path, str]:
    out: dict[Path, str] = {}
    template = ROOT / "agent-config" / "claude-md.template"
    out[ROOT / "CLAUDE.md"] = template.read_text(encoding="utf-8")
    for sub, dest in (("rules", "rules"), ("agents", "agents")):
        for src in sorted((ROOT / "agent-config" / sub).glob("*.md")):
            out[ROOT / ".claude" / dest / src.name] = _with_header(
                src, src.read_text(encoding="utf-8")
            )
    skills = ROOT / ".agents" / "skills"
    for src in sorted(p for p in skills.rglob("*") if p.is_file()):
        text = src.read_text(encoding="utf-8")
        if src.suffix == ".md":
            text = _with_header(src, text)
        out[ROOT / ".claude" / "skills" / src.relative_to(skills)] = text
    return out


def managed_dirs() -> list[Path]:
    return [ROOT / ".claude" / d for d in ("rules", "agents", "skills")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="report drift, write nothing")
    args = parser.parse_args()

    expected = expected_files()
    existing = {p for d in managed_dirs() if d.exists() for p in d.rglob("*") if p.is_file()}
    stale = sorted(existing - set(expected))
    drift = sorted(
        p for p, text in expected.items() if not p.exists() or p.read_text("utf-8") != text
    )

    if args.check:
        for p in drift:
            print(f"drift: {p.relative_to(ROOT)}")
        for p in stale:
            print(f"stale: {p.relative_to(ROOT)}")
        if drift or stale:
            print("Run: uv run python scripts/sync_agent_config.py", file=sys.stderr)
            return 1
        print("agent-config adapters are in sync")
        return 0

    for p in stale:
        p.unlink()
    for p in drift:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(expected[p], encoding="utf-8")
        print(f"wrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
