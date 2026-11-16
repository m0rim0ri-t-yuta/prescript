#!/usr/bin/env bash
# The behaviour-layer demo: an operating procedure written as states (the ASM chart), drawn as one
# loop diagram per state, then played through the plant built from the same netlist.
# Usage: ./scripts/demo-procedure.sh
#
#   1 verify     — every step of `stop-cdu-A` is a mode; the static checks run in each (exit 0)
#   2 draw       — one SVG per state and an index.html storyboard
#   3 sim        — the steps on the time axis through the Phase 2 testbench (exit 0)
#   4 low tank   — expansion-tank fill pressure 100 -> 10 kPa: the static checks still pass
#                  (exit 0), and the testbench finds the cavitation at the step that causes it (exit 1)
#
# Like scripts/demo.sh it asserts the shape of the story (exit codes, a P-01 FAIL in step 4), never
# the figures. The reference design is never modified.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
reference="${PRESCRIPT_DEMO_NETLIST:-$root/examples/gb200-1su/netlist.yaml}"
procedure="${PRESCRIPT_DEMO_PROCEDURE:-stop-cdu-A}"
tmp="${TMPDIR:-/tmp}"
work="${tmp%/}/prescript-demo-procedure"

# run <label> <expected exit> <command...> — print the label, the summary line and the exit code
run() {
  local label="$1" want="$2" code=0 out summary
  shift 2
  out="$(cd "$root" && uv run --quiet prescript "$@" 2>&1)" || code=$?
  summary="$(grep -E '^PASS ' <<<"$out" | head -1 || true)"
  if [[ -z "$summary" ]] && grep -q '^wrote ' <<<"$out"; then
    summary="wrote $(grep -c '^wrote ' <<<"$out") files"
  fi
  printf '%-30s %-42s exit %d\n' "$label" "${summary:-(no summary line)}" "$code"
  if [[ "$code" != "$want" ]]; then
    echo "demo-procedure.sh: $label expected exit $want, got $code." >&2
    echo "$out" >&2
    exit 1
  fi
  LAST="$out"
}

rm -rf "$work"
mkdir -p "$work"
cp "$reference" "$work/01-reference.yaml"
sed 's/fill_kpa: 100,/fill_kpa: 10,/' "$work/01-reference.yaml" >"$work/02-low-tank.yaml"
if cmp -s "$work/01-reference.yaml" "$work/02-low-tank.yaml"; then
  echo "demo-procedure.sh: nothing matched 'fill_kpa: 100,' — update this script." >&2
  exit 1
fi

echo "Prescript demo — procedure $procedure: states -> diagrams -> simulation"
echo "files: $work"
echo

run "1 verify (static, per step)" 0 verify "$work/01-reference.yaml"
run "2 draw (one frame per state)" 0 draw "$work/01-reference.yaml" \
  --procedure "$procedure" -o "$work/storyboard"
echo "    storyboard: $work/storyboard/index.html"
run "3 sim (steps on a time axis)" 0 sim "$work/01-reference.yaml" -p "$procedure" --runs 3 \
  --plot "$work/sim-reference.svg"
awk '/^timeline/,/^$/' <<<"$LAST" | sed 's/^/    /'
echo "    chart: $work/sim-reference.svg"
echo
run "4a low tank: verify" 0 verify "$work/02-low-tank.yaml"
run "4b low tank: sim" 1 sim "$work/02-low-tank.yaml" -p "$procedure" --runs 3 \
  --plot "$work/sim-low-tank.svg"
if ! grep -qE '^FAIL +P-01@' <<<"$LAST"; then
  echo "demo-procedure.sh: step 4b was expected to report cavitation (P-01) and did not." >&2
  echo "$LAST" >&2
  exit 1
fi
awk '/^FAIL +P-01@run-00/ { f = 1; print; next } /^(PASS|FAIL|WARN|UNRUN) / { f = 0 }
     f && /^ +- / { print }' <<<"$LAST" | sed 's/^/    /'
echo "    chart: $work/sim-low-tank.svg"
echo
echo "The static checks pass the low tank; the testbench fails it at the step that exposes it."
