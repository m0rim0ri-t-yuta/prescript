#!/usr/bin/env bash
# Run the W4 demo end to end: the reference design is green, a GPU refresh turns it red, and
# upsizing the cooling loop turns it green again. Usage: ./scripts/demo.sh
#
# This asserts the shape of the story — exit 0, then exit 1 with findings, then exit 0 — and never
# the totals, which move whenever a check routine lands. The measured figures live in
# docs/ROADMAP.md ("Demo script (W4)"); the reference design itself is never modified.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# PRESCRIPT_DEMO_NETLIST exists for tests/test_demo.py; a demo uses the reference design.
reference="${PRESCRIPT_DEMO_NETLIST:-$root/examples/gb200-1su/netlist.yaml}"
tmp="${TMPDIR:-/tmp}"
work="${tmp%/}/prescript-demo"

# edit <in> <out> <sed expression>... — apply each expression and fail if one matched nothing, so a
# reformatted netlist stops the demo instead of silently showing the wrong thing.
edit() {
  local in="$1" out="$2" expr before
  shift 2
  cp "$in" "$out"
  for expr in "$@"; do
    before="$(cat "$out")"
    sed "$expr" "$out" >"$out.tmp"
    mv "$out.tmp" "$out"
    if [[ "$before" == "$(cat "$out")" ]]; then
      echo "demo.sh: nothing matched '$expr' in $(basename "$in")." >&2
      echo "demo.sh: the netlist text changed — update scripts/demo.sh." >&2
      exit 1
    fi
  done
}

# step <label> <netlist> <expected exit> [show-findings]
step() {
  local label="$1" netlist="$2" want="$3" show="${4:-}" code=0 out summary
  out="$(cd "$root" && uv run --quiet prescript verify "$netlist" 2>&1)" || code=$?
  summary="$(grep -E '^PASS ' <<<"$out" || echo '(no summary line)')"
  printf '%-24s %-42s exit %d\n' "$label" "$summary" "$code"
  if [[ "$code" != "$want" ]]; then
    echo "demo.sh: $label expected exit $want, got $code." >&2
    echo "$out" >&2
    exit 1
  fi
  if [[ -n "$show" ]]; then
    if ! grep -qE '^FAIL ' <<<"$out"; then
      echo "demo.sh: $label was expected to report findings and reported none." >&2
      echo "$out" >&2
      exit 1
    fi
    # Print each FAIL with its own evidence only. WARN and UNRUN blocks also carry indented items;
    # they must not be shown under a FAIL they do not belong to.
    awk '/^FAIL / { f = 1; print; next }
         /^(PASS|WARN|UNRUN) / { f = 0; next }
         f && /^ +(- |… )/ { print }' <<<"$out" | sed 's/^/    /'
  fi
}

rm -rf "$work"
mkdir -p "$work"
cp "$reference" "$work/01-baseline.yaml"

echo "Prescript demo — see docs/ROADMAP.md, \"Demo script (W4)\""
echo "netlists: $work"
echo

step "1 reference design" "$work/01-baseline.yaml" 0

# A GPU refresh in an existing hall: one parameter in the rack block.
edit "$work/01-baseline.yaml" "$work/02-refresh.yaml" 's/heat_kw: 150,/heat_kw: 200,/'
step "2 racks 150->200 kW" "$work/02-refresh.yaml" 1 show-findings

# The fix: a larger CDU, larger mains and larger rack manifolds.
edit "$work/02-refresh.yaml" "$work/03-upsized.yaml" \
  's/rating_kw: 1500, rating_lpm: 2300/rating_kw: 1800, rating_lpm: 2800/' \
  's/dn_mm: 150}/dn_mm: 200}/' \
  's/manifold_lpm: 300}/manifold_lpm: 350}/'
step "3 loop upsized" "$work/03-upsized.yaml" 0

echo
echo "Green -> red -> green. The reference design was not touched."
echo "For the form CI posts on a pull request:"
echo "  uv run prescript verify -f md $work/02-refresh.yaml"
