# Project Conventions & Known Gotchas

## Tooling

- **uv only.** `uv sync`, `uv run …`, `uv add …`. No `pip install` into the project env.
- **Lint and types are gates**: `ruff check`, `ruff format --check`, `mypy --strict` on `src/`.
  A warning you silence needs a comment saying why.
- Python ≥ 3.12. Use `from __future__ import annotations` and pydantic v2 models for IR types.

## Code

- Engineering units live in field names (`rating_kva`, `rating_a`, `voltage_kv`, `start_time_s`).
  Never store a bare number whose unit is implied.
- IDs are strings and case-sensitive; side tags are matched as whole `-A`/`-B` segments.
- Checks are pure functions of `(Design, ModeState, args)`. No I/O, no globals, no randomness.

## Triaging a red check

- `cancelled` ≠ `failed`: CI uses `cancel-in-progress`, so a newer push cancels the older run.
  Judge the latest run per head SHA.

## Configuration safety

- `.claude/settings.local.json` is personal and never committed.
- Edit common instructions only in `AGENTS.md`, rules only in `agent-config/rules`, agents only in
  `agent-config/agents`, skills only in `.agents/skills`; then run the sync script.
