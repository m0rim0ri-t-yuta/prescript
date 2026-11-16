<!-- GENERATED from agent-config/rules/review-governance.md by scripts/sync_agent_config.py. Edit the source. -->

# Review & Merge Governance

## Principle

The repository owner is the sole reviewer-of-record. Agents prepare PRs. The owner merges them,
or tells an agent to merge — the decision stays the owner's either way.

## Rules

1. **Agents merge only on the owner's explicit instruction.** Without one, an agent prepares the
   PR and stops; `gh pr merge` is the owner's. An instruction covers the PRs it names and that
   session only — it does not carry over to the next task. **No pushing to `main`** in either
   case: branch protection requires a PR and green CI, and agents do not change branch
   protection or enable auto-merge.
2. **A PR is ready for the owner when**: CI is green, the PR template is filled in, the body names
   the `prescript verify` result on the reference design before and after (paste the summary line), and
   every changed behaviour has a test.
3. **Merge method**: squash. The squash title is the PR title (Conventional Commits).
