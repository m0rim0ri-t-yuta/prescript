<!-- GENERATED from agent-config/rules/team-agents.md by scripts/sync_agent_config.py. Edit the source. -->

# Agents & Parallel Work

- Delegate bounded exploration, review, test analysis and summarization when it reduces context
  noise. Read-only agents may share the current checkout.
- Every editing agent owns a distinct worktree, branch and PR with its own Issue(s), except
  `sonnet-worker`, which edits inside the parent's worktree and branch.
- Give each agent its own files. `src/keel/ir.py` is locked to one agent at a time: every stage
  compiles against it. Parallelise only file-disjoint, independently reviewable work — new check
  modules are the natural unit.
- `pyproject.toml`, `uv.lock`, `.gitignore`, CI and central agent documentation belong to the
  integration owner (the lead session), who also sets merge order.
