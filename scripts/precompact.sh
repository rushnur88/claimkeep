#!/usr/bin/env bash
# ClaimKeep PreCompact hook.
#
# Fail-open by design: a memory layer must never block compaction, so this
# script always exits 0. Errors still go to stderr so a broken install is
# visible instead of silent.
#
# Runs straight from the plugin checkout — no pip install required, because
# CLAUDE_PLUGIN_ROOT is the repository root and the package lives there.
set -uo pipefail

ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

if command -v claimkeep >/dev/null 2>&1; then
  claimkeep precompact || true
else
  python3 -m claimkeep precompact || true
fi

exit 0
