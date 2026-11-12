# Safety Rules

## Git

- Force-push (incl. `+refspec`), deleting `main`, `--no-verify`, and `git commit -n` are denied by
  `scripts/agent_hooks/block_unsafe_git.py` (Claude PreToolUse hook) and `.claude/settings.json`.
  Do not route around them. If a hook is wrong, fix the hook in its own PR.

## Secrets

- Never commit `.env*`, credentials, tokens or keys. `gitleaks` runs in pre-commit and CI.
- GitHub Actions secrets are referenced only through `${{ secrets.* }}`, never echoed.

## Data

- Only public data enters the repository (`public-data.md`).

## Dependencies

- Add a runtime dependency only with a one-line reason in the PR body; prefer the standard library.
  `uv.lock` is committed and owned by the integration owner (`team-agents.md`).
