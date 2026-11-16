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
| `uv run prescript draw … --procedure stop-cdu-A -o frames/`    | One SVG per step + `index.html`       |
| `uv run prescript sim [--seed N --runs K]`                | Phase 1 testbench (`SIMULATION.md`)   |
| `uv run prescript sim netlist.yaml -p stop-cdu-A --plot sim.svg` | Phase 2: the netlist's loop through a procedure |
| `./scripts/demo.sh`                                       | W4 demo: green → red → green (below)  |
| `./scripts/demo-procedure.sh`                             | Procedure → diagrams → simulation     |
| `./scripts/ci_netlist_diff.sh <base-sha> diff.md`         | Reproduce CI's diff comment locally   |
| `uv run python scripts/ci_comment.py diff.md report.md c.md` | …and the bounded comment CI posts     |
| `uv run pytest`                                           | Tests                                 |
| `uv run ruff check . && uv run ruff format --check .`     | Lint + format                         |
| `uv run mypy`                                             | Strict type check of `src/`           |
| `uv run python scripts/sync_agent_config.py [--check]`    | Regenerate / verify Claude adapters   |
| `./scripts/sync_labels.sh`                                | Push `.github/labels.yml` to GitHub   |

`prescript verify` exit codes: **0** every assertion passed, **1** at least one `FAIL` (or, with
`--strict`, an `UNRUN`), **2** the netlist could not be read — a malformed file, a bad grammar
version, a missing `provenance`, a rating that is not a number. CI can tell a red design from an
unreadable one by the code alone; a netlist error prints one line and no report.

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
  pushing to `main` and `gh pr merge` — but only in sessions whose project directory is this repo,
  so it is a second layer under the behavioural gate (`agent-config/rules/safety.md`).

## CI (`.github/workflows/`)

- `ci.yml` — lint, format, mypy, pytest, agent-config drift, `prescript verify` on the reference design.
- `prescript-verify.yml` — on PRs touching `examples/**`, `src/prescript/**`, this workflow or
  `scripts/ci_netlist_diff.sh` (the last two so a change to the job runs the job): posts one
  sticky comment, the change list above the verdict. `scripts/ci_netlist_diff.sh` runs
  `prescript diff -f md` between the base commit's netlist and this one for every netlist the
  PR *modifies* (added, deleted and renamed ones are skipped — there is nothing to compare),
  and `prescript verify -f md` on the reference design supplies the verdict below it. Only a
  `FAIL` from verify turns the job red; the diff states facts and never a verdict. The job
  needs `fetch-depth: 0`, because the base netlist is read with `git show`.
  `scripts/ci_comment.py` joins the two inside GitHub's comment limit (65536 characters, which
  the API rejects a body for exceeding — and it would reject the verdict along with it). Over the
  limit the change list loses whole lines from its end, the report stays whole, and the comment
  says what was cut and where to read it; the full text goes to the job log. Pass `--limit` to
  try a smaller bound by hand.
- `gitleaks.yml` — full-history secret scan with the gitleaks CLI (job `scan`).
