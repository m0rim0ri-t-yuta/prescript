# Development

## Setup

```bash
# Python ≥ 3.12, uv (https://docs.astral.sh/uv/) and gitleaks (macOS: brew install gitleaks)
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
| `uv run prescript diff before.yaml after.yaml`                 | What changed, after elaboration       |
| `uv run prescript diff -f md …` / `-f json`                    | Markdown for PR comments / JSON       |
| `uv run prescript draw … -o loop.svg`                          | Loop diagram as SVG                   |
| `uv run prescript draw … --mode maint-cdu-A`                   | …with one mode's states on it         |
| `uv run prescript sim [--seed N --runs K]`                | Dynamic testbench (`SIMULATION.md`)   |
| `./scripts/demo.sh`                                       | W4 demo: green → red → green (below)  |
| `./scripts/ci_netlist_diff.sh <base-sha> diff.md`         | Reproduce CI's diff comment locally   |
| `uv run pytest`                                           | Tests                                 |
| `uv run ruff check . && uv run ruff format --check .`     | Lint + format                         |
| `uv run mypy`                                             | Strict type check of `src/`           |
| `uv run python scripts/sync_agent_config.py [--check]`    | Regenerate / verify Claude adapters   |
| `./scripts/sync_labels.sh`                                | Push `.github/labels.yml` to GitHub   |

## Demo

`./scripts/demo.sh` runs the W4 walkthrough from `ROADMAP.md` on copies of the reference design:
the design as it is, a GPU refresh (racks 150 → 200 kW) and an upsized cooling loop. It prints each
step's summary line and exit code, and the evidence under every `FAIL`. The reference design is never
modified; the copies are left in `$TMPDIR/prescript-demo`.

It checks the shape of the story — exit 0, then exit 1 with findings, then exit 0 — not the totals,
which change whenever a check routine lands. If a step stops matching (the netlist text changed, or a
step no longer goes the expected colour) the script stops with the reason; `tests/test_demo.py` runs
it in CI.

## Hooks

- **pre-commit**: ruff, ruff-format, gitleaks on staged changes (warns and skips if the binary is
  missing — the CI `scan` job is the gate), whitespace/YAML checks.
- **pre-push**: mypy, pytest, agent-config drift check — the same gates as CI.
- **Claude PreToolUse**: `scripts/agent_hooks/block_unsafe_git.py` denies `--no-verify`, force-push,
  pushing to `main` and `gh pr merge`.

## CI (`.github/workflows/`)

- `ci.yml` — lint, format, mypy, pytest, agent-config drift, `prescript verify` on the reference design.
- `prescript-verify.yml` — on PRs touching `examples/**` or `src/prescript/**`: posts one
  sticky comment, the change list above the verdict. `scripts/ci_netlist_diff.sh` runs
  `prescript diff -f md` between the base commit's netlist and this one for every netlist the
  PR *modifies* (added, deleted and renamed ones are skipped — there is nothing to compare),
  and `prescript verify -f md` on the reference design supplies the verdict below it. Only a
  `FAIL` from verify turns the job red; the diff states facts and never a verdict. The job
  needs `fetch-depth: 0`, because the base netlist is read with `git show`.
- `gitleaks.yml` — full-history secret scan with the gitleaks CLI (job `scan`).
