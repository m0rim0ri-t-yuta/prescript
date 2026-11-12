# AGENTS.md

## Configuration

- **SSOT**: this file + `agent-config/rules/*.md`; agents in `agent-config/agents/*.md`; skills in
  `.agents/skills/*/SKILL.md`; docs index `docs/README.md`.
- `CLAUDE.md`, `.claude/rules/`, `.claude/agents/` and `.claude/skills/` are **generated adapters**.
  Edit the SSOT, then run `uv run python scripts/sync_agent_config.py`; CI fails on drift
  (`--check`).
- A new rule file needs `paths:` frontmatter unless it applies to every conversation.
- These rules can be stale. Precedence: codebase > Issues/PRs > `docs/*.md` and these rules. When a
  rule contradicts the repo, say so, act on the repo, and fix the rule in the same PR.

## Pre-authorized / Hard gates

Pre-authorized without asking: reading, editing, running tests and linters, creating an issue and a
worktree, committing, pushing a branch, opening a PR, and fixing your own red CI.
Hard gates — stop and ask: **merging** (the owner merges), force-push, `--no-verify`, adding a
non-public data source to `examples/`, publishing a release or tag, and changing `LICENSE`.
Everything else: act, then report.

## Project Overview

Prescript is a spec-as-code and verification pipeline for physical power systems, borrowing the
discipline of hardware description languages (Verilog/SystemVerilog): a design is written as a
netlist, elaborated into an IR, and checked by assertions across operating modes on every pull
request. The PoC targets one US data-center scalable unit (GB200 NVL72, 1 SU, Tier III, 2N).
Roadmap and scope: `docs/ROADMAP.md`.

## Architecture

Non-obvious constraints only — everything else is discoverable from the repo
(`docs/ARCHITECTURE.md`).

- **Pipeline**: `netlist.yaml` → `loader` (parse + block elaboration) → `ir.Design` →
  `modes` (per-mode energization) → `checks` → `report`. Each stage consumes only the previous
  stage's output; checks never read YAML.
- **Never pass on missing data**: a check that touches a `null` rating returns `UNRUN`, never
  `PASS`. A check that is not implemented also returns `UNRUN`. This is the product's core promise
  (`agent-config/rules/verification-semantics.md`).
- **Provenance is mandatory** on every rated element: a spec cell, a public source, or the literal
  `assumed`. Missing provenance is a loader error, not a warning.
- **Public data only**: everything under `examples/` comes from public reference designs, standards
  or explicit assumptions (`agent-config/rules/public-data.md`).
- **Grammar SSOT** is `docs/PRESCRIPT-LANGUAGE.md`; the loader implements it. Change both in one PR.
- **No physics we cannot defend**: short-circuit duty, harmonics and transient stability stay
  `UNRUN` (or simplified with the method named in the result) until a validated method exists.
  Industry simulators are integration targets, not things we re-implement.

## Key Paths

- `src/prescript/ir.py` — IR (pydantic): nodes, edges, devices, modes, assertions
- `src/prescript/loader.py` — YAML → IR, block elaboration, validation
- `src/prescript/modes.py` — per-mode state resolution and energization
- `src/prescript/checks/` — one module per assertion routine; registry in `checks/__init__.py`
- `src/prescript/cli.py` — `prescript verify` / `prescript elaborate`
- `examples/gb200-1su/netlist.yaml` — the reference design

## Quick Start

`uv sync` · `uv run prescript verify examples/gb200-1su/netlist.yaml` · `uv run pytest` ·
`uv run ruff check . && uv run mypy`. Everything else: `docs/DEVELOPMENT.md`.

## Agent Context

- **GitHub Repository**: `OWNER/prescript` (rename in this line if the repo moves)
- **Review policy**: agents open PRs; the owner reviews and merges (`review-governance.md`).
- **Issue conventions**: SSOT `issue-hygiene.md`; label taxonomy `docs/ISSUE_MANAGEMENT.md`.
- **Language Policy**:
  - English: `docs/*.md`, `AGENTS.md`, `agent-config/**`, code/comments, commit messages,
    **PR titles**, Issue titles, everything under `examples/`
  - Japanese OK: GitHub Issue bodies, **PR descriptions/body**
  - PR title format: Conventional Commits — `<type>(<scope>): <subject> #<issue>`
    (e.g. `feat(checks): add loading assertion #12`). Types: `feat` / `fix` / `chore` / `docs` /
    `refactor` / `test` / `perf`. Scopes: `ir`, `loader`, `modes`, `checks`, `report`, `cli`,
    `render`, `examples`, `ci`, `docs`, `agents`.
