#!/usr/bin/env bash
# pre-commit: scan staged changes with a locally installed gitleaks binary.
# Fails open with a loud warning when gitleaks is not installed: the `gitleaks / scan` CI job scans
# the full history and is a required check on main, so a missing local binary never ships a leak.
set -euo pipefail
if ! command -v gitleaks >/dev/null 2>&1; then
  echo "warn: gitleaks not installed; staged changes not scanned locally (CI will scan)." >&2
  echo "      macOS: brew install gitleaks" >&2
  exit 0
fi
exec gitleaks git --pre-commit --staged --redact --no-banner --exit-code 1 .
