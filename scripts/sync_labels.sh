#!/usr/bin/env bash
# Create/update GitHub labels from .github/labels.yml. Usage: ./scripts/sync_labels.sh [owner/repo]
set -euo pipefail
repo="${1:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
uv run python - "$repo" <<'PY'
import subprocess, sys, yaml
repo = sys.argv[1]
for label in yaml.safe_load(open(".github/labels.yml", encoding="utf-8")):
    subprocess.run(
        ["gh", "label", "create", label["name"], "--repo", repo, "--force",
         "--color", label["color"], "--description", label.get("description", "")],
        check=True,
    )
    print("synced", label["name"])
PY
