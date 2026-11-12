# Review & Merge Governance

## Principle

The repository owner is the sole reviewer-of-record. Agents prepare PRs; the owner merges.

## Rules

1. **Agents never merge.** No `gh pr merge`, no pushing to `main`. Branch protection on `main`
   requires a PR and green CI; agents do not change branch protection.
2. **A PR is ready for the owner when**: CI is green, the PR template is filled in, the body names
   the `keel verify` result on the reference design before and after (paste the summary line), and
   every changed behaviour has a test.
3. **Merge method**: squash. The squash title is the PR title (Conventional Commits).
