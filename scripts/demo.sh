#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python - <<'PY'
import json
from opsjobs.domain import analyze
print(json.dumps({"fixture_demo": analyze("Synthetic reference workload\nDurable jobs")}, indent=2))
PY
.venv/bin/python scripts/lab.py integration --lab-id ops-container-platform-reference
if .venv/bin/python scripts/lab.py integration --lab-id unrelated --execute --confirm unrelated; then
  echo 'FAIL: foreign target was accepted' >&2
  exit 1
fi
printf '%s\n' 'Foreign target rejected. This controller demo allocated no VM or container.'
