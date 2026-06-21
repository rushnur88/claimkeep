#!/usr/bin/env bash
set -euo pipefail

if command -v claimkeep >/dev/null 2>&1; then
  CK="claimkeep"
else
  CK="python3 -m claimkeep"
fi

EVENT="${CLAUDE_HOOK_EVENT_NAME:-SessionStart}"
$CK postcompact --event "$EVENT" || true
exit 0
