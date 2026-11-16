<!-- GENERATED from agent-config/rules/safety.md by scripts/sync_agent_config.py. Edit the source. -->

# Safety Rules

## Git

- Force-push (incl. `+refspec`), deleting `main`, `--no-verify`, `git commit -n` and `gh pr merge`
  are hard gates you keep yourself: stop and ask the owner, every time. The rule is the gate.
- `scripts/agent_hooks/block_unsafe_git.py` (Claude PreToolUse hook) and the `permissions.deny`
  list in `.claude/settings.json` are a second layer only, and they bind **only when this repo is
  the session's project directory**: the hook is registered as
  `$CLAUDE_PROJECT_DIR/scripts/agent_hooks/block_unsafe_git.py`, and `.claude/settings.json` is
  read for the project directory. Drive a prescript worktree from another repo's session and
  neither file is loaded, so the same commands run unblocked. A push that went through is not
  evidence that it was allowed.
- Do not route around either layer. If a hook is wrong, fix the hook in its own PR.

## Secrets

- Never commit `.env*`, credentials, tokens or keys. `gitleaks` runs in pre-commit and CI.
- GitHub Actions secrets are referenced only through `${{ secrets.* }}`, never echoed.

## Data

- Only public data enters the repository (`public-data.md`).

## Dependencies

- Add a runtime dependency only with a one-line reason in the PR body; prefer the standard library.
  `uv.lock` is committed and owned by the integration owner (`team-agents.md`).
