#!/usr/bin/env bash
# ClaimKeep UserPromptSubmit hook — searches every stored brief for this turn.
#
# The other hooks re-inject the newest brief. This one reaches the rest of the
# corpus, which has always been searchable and was never searched: `recall`
# existed as a command a human could type, and the agent is who needs it.
#
# Quiet by design. It prints nothing unless a stored claim actually contains
# what was asked about, caps the result at a few short lines, and never
# surfaces a value that was later corrected.
#
# Fail-open (always exits 0); errors go to stderr.
# Off:  CLAIMKEEP_RECALL_HOOK=0
set -uo pipefail

ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

if command -v claimkeep >/dev/null 2>&1; then
  claimkeep recall-hook || true
else
  python3 -m claimkeep recall-hook || true
fi

exit 0
