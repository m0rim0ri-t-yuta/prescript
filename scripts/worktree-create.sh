#!/usr/bin/env bash
# Usage: ./scripts/worktree-create.sh <issue-id> <slug> [feature|fix|chore|docs]
set -euo pipefail

id="${1:?issue id required}"
slug="${2:?slug required}"
type="${3:-feature}"
case "$type" in feature|fix|chore|docs) ;; *) echo "type must be feature|fix|chore|docs" >&2; exit 1;; esac
[[ "$slug" =~ ^[a-z0-9-]+$ ]] || { echo "slug must be kebab-case" >&2; exit 1; }

root="$(git rev-parse --show-toplevel)"
name="$(basename "$root")"
branch="${type}/${id}-${slug}"
dir="$(dirname "$root")/${name}-worktrees/${type}-${id}-${slug}"

git -C "$root" fetch origin main --quiet || echo "warn: fetch failed; branching from local main" >&2
base="origin/main"; git -C "$root" rev-parse --verify --quiet "$base" >/dev/null || base="main"
git -C "$root" worktree add -b "$branch" "$dir" "$base"

cd "$dir"
uv sync --quiet
uv run pre-commit install --hook-type pre-commit --hook-type pre-push >/dev/null

mkdir -p .claude
cat > .claude/worktree-context.md <<EOF
# Worktree context
- branch: ${branch}
- issue: #${id}
- created-from: $(git rev-parse --short "$base")
- scope: files needed for #${id} only; ask before touching src/keel/ir.py, pyproject.toml, uv.lock, CI.
EOF

echo "Worktree ready: $dir"
echo "Branch: $branch"
