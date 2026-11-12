# Golden Path (Mandatory Lifecycle)

Every task follows these steps in order.

1. **Issue**: search first, create if none, self-assign, apply metadata (`issue-hygiene.md`).
   Related issues may share one branch/PR: list every `Closes #<id>` and name the branch after the
   primary issue. Sub-agents report findings instead of filing (`issue-hygiene.md` §6).
2. **Worktree + Branch**: `./scripts/worktree-create.sh <id> <slug> [type]` creates
   `../keel-power-worktrees/<type>-<id>-<slug>/` and cuts `<type>/<id>-<slug>` from `main`
   (`feature`/`fix`/`chore`/`docs`). It runs `uv sync` and installs the pre-commit and pre-push
   hooks — never hand-bootstrap a worktree, or git silently runs no hooks. Work only inside it.
3. **Develop**: write code + tests, then run the affected surface, not only the suite — at minimum
   `uv run keel verify examples/gb200-1su/netlist.yaml` and read the table.

   > An Issue body is a hypothesis. Run its reproduction command before implementing. No
   > reproduction: comment and stop.

4. **Pre-push**: the pre-push hook runs ruff, mypy, pytest and the agent-config drift check —
   the same gates as CI. Never skip it (`safety.md`).
5. **PR**: push the branch and open the PR — title per `AGENTS.md` → Language Policy, body (Japanese
   OK) with `Closes #<id>`, filled-in PR template.
6. **CI**: `gh pr checks <PR>` — every check must pass. A red check is yours to fix: read the job
   log, fix on this branch, push, re-check. Hand back only for a cause outside your diff.
7. **Merge**: the owner merges (`review-governance.md`). After merge: `git worktree remove` the
   worktree and pull `main`.

Update docs in the same PR when behaviour they describe changes (`doc-update.md`).
