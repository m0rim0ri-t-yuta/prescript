# Development

## Setup

```bash
# Python ≥ 3.12 and uv (https://docs.astral.sh/uv/)
uv sync
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```

For Issue work use `./scripts/worktree-create.sh <id> <slug> [type]` instead — it does both.

## Commands

| Command                                                   | What                                  |
| --------------------------------------------------------- | ------------------------------------- |
| `uv run prescript verify examples/gb200-1su/netlist.yaml`      | Run all assertions (text)             |
| `uv run prescript verify -f md …` / `-f json`                  | Markdown for PR comments / JSON       |
| `uv run prescript verify --strict …`                           | Also fail on `UNRUN`                  |
| `uv run prescript elaborate …`                                 | Dump the elaborated IR                |
| `uv run pytest`                                           | Tests                                 |
| `uv run ruff check . && uv run ruff format --check .`     | Lint + format                         |
| `uv run mypy`                                             | Strict type check of `src/`           |
| `uv run python scripts/sync_agent_config.py [--check]`    | Regenerate / verify Claude adapters   |
| `./scripts/sync_labels.sh`                                | Push `.github/labels.yml` to GitHub   |

## Hooks

- **pre-commit**: ruff, ruff-format, gitleaks, whitespace/YAML checks.
- **pre-push**: mypy, pytest, agent-config drift check — the same gates as CI.
- **Claude PreToolUse**: `scripts/agent_hooks/block_unsafe_git.py` denies `--no-verify`, force-push,
  pushing to `main` and `gh pr merge`.

## CI (`.github/workflows/`)

- `ci.yml` — lint, format, mypy, pytest, agent-config drift, `prescript verify` on the reference design.
- `prescript-verify.yml` — on PRs touching `examples/**`: posts the Markdown report as a sticky comment.
- `gitleaks.yml` — secret scan.
