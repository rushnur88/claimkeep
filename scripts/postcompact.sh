#!/usr/bin/env bash
# ClaimKeep SessionStart / PostCompact hook — re-injects the newest brief.
#
# Fail-open by design (always exits 0); errors go to stderr.
# Runs straight from the plugin checkout — no pip install required.
set -uo pipefail

ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

EVENT="${CLAUDE_HOOK_EVENT_NAME:-SessionStart}"

if command -v claimkeep >/dev/null 2>&1; then
  claimkeep postcompact --event "$EVENT" || true
else
  python3 -m claimkeep postcompact --event "$EVENT" || true
fi

exit 0
