---
name: worktree-create
description: Create an isolated git worktree and branch for an Issue, with dependencies and git hooks installed. Use at step 2 of the Golden Path, before editing anything for an Issue.
---

# worktree-create

```bash
./scripts/worktree-create.sh <issue-id> <slug> [feature|fix|chore|docs]
```

The script:

1. fetches `origin/main` and cuts `<type>/<id>-<slug>`;
2. creates `../keel-power-worktrees/<type>-<id>-<slug>/`;
3. runs `uv sync` and installs the pre-commit and pre-push hooks;
4. writes `.claude/worktree-context.md` (branch, issue, scope) in the worktree.

Then `cd` into the printed path and work only there. Do not hand-bootstrap a worktree: without
step 3 git runs no hooks and a push goes out unchecked.

Clean up after merge: `git worktree remove ../keel-power-worktrees/<dir>`.
