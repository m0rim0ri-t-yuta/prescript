---
paths:
  - 'src/keel/checks/**'
  - 'src/keel/modes.py'
  - 'src/keel/report.py'
  - 'tests/**'
---

<!-- GENERATED from agent-config/rules/verification-semantics.md by scripts/sync_agent_config.py. Edit the source. -->

# Verification Semantics

The verifier's credibility is the product. These invariants are tested; do not weaken them.

1. **Status set is closed**: `PASS`, `FAIL`, `WARN`, `UNRUN`. No other status, no booleans.
2. **`null` never passes.** If any value a check needs is `null`, the result is `UNRUN` with the
   missing fields listed in `missing`. Do not substitute a default.
3. **Not implemented never passes.** An unregistered or stub routine returns `UNRUN` with reason
   `not implemented`.
4. **Severity only downgrades `FAIL` to `WARN`.** It never touches `PASS`/`UNRUN`.
5. **Every result names its evidence**: the elements it examined (`subjects`) and, for a `FAIL`,
   the offending ones. A `FAIL` without evidence is a bug.
6. **Simplified methods say so.** A check that uses a simplified method (e.g. a screening estimate)
   names the method in `detail` and is never presented as a study result.
7. **Exit codes**: `keel verify` exits 1 on any `FAIL`; `--strict` also exits 1 on any `UNRUN`.
8. **One routine per module** under `src/keel/checks/`, registered in `checks/__init__.py`, with a
   test that shows at least one `PASS`, one `FAIL` and one `UNRUN` (where `UNRUN` is reachable).
