#!/usr/bin/env bash
# Write a `prescript diff` section for every netlist this pull request modifies.
# Usage: ./scripts/ci_netlist_diff.sh <base-sha> <out-file> [pathspec]
#
# .github/workflows/prescript-verify.yml puts the result above the verify report in one sticky
# comment: what changed, then the verdict. The diff never decides pass or fail — `prescript verify`
# does (agent-config/rules/verification-semantics.md).
#
# Only a *modified* netlist has a base side and a head side, so one the PR adds, deletes or renames
# is skipped on purpose: introducing a design must not fail the job. With nothing to compare the
# out-file is left empty and the comment is the verify report alone. A netlist the base cannot
# elaborate becomes a note in the comment rather than a red job, because the verdict on the head
# side is the verify step's business.
set -euo pipefail

base="${1:?base sha required}"
out="${2:?out-file required}"
pathspec="${3:-examples/**/netlist.yaml}"
ERROR_TAIL_LINES=12

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Run git where the checkout is (the Actions workspace) but prescript from this repo, so the
# script also runs against a throwaway repository in tests/test_ci_netlist_diff.py.
prescript=(uv run --quiet --project "$root" prescript)

: >"$out"

if ! git rev-parse --verify --quiet "${base}^{commit}" >/dev/null; then
  echo "ci_netlist_diff.sh: $base is not in this clone — actions/checkout needs fetch-depth: 0." >&2
  exit 0
fi

changed="$(git diff --name-only --diff-filter=M "$base" HEAD -- "$pathspec")"
if [[ -z "$changed" ]]; then
  echo "ci_netlist_diff.sh: no modified netlist matching '$pathspec' since $base — nothing to diff."
  exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# note <netlist> — say in the comment why a netlist could not be compared. Only the tail of the
# error goes in: a YAML parse error arrives as a rich traceback, and the comment wants the reason.
note() {
  printf '### Prescript diff — `%s`\n\n`prescript diff` could not compare this netlist against the base. The last lines of its error output:\n\n```\n%s\n```\n\n' \
    "$1" "$(tail -n "$ERROR_TAIL_LINES" "$tmp/err")" >>"$out"
}

while IFS= read -r netlist; do
  [[ -n "$netlist" ]] || continue
  before="$tmp/base-$(printf '%s' "$netlist" | tr '/' '_')"
  if ! git show "${base}:${netlist}" >"$before" 2>"$tmp/err"; then
    note "$netlist"
    continue
  fi
  if "${prescript[@]}" diff -f md "$before" "$PWD/$netlist" >"$tmp/section" 2>"$tmp/err"; then
    { cat "$tmp/section"; printf '\n'; } >>"$out"
    echo "ci_netlist_diff.sh: diffed $netlist against $base."
  else
    note "$netlist"
  fi
done <<EOF
$changed
EOF
