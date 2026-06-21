#!/usr/bin/env bash
set -euo pipefail

if command -v claimkeep >/dev/null 2>&1; then
  CK="claimkeep"
else
  CK="python3 -m claimkeep"
fi

$CK precompact || true
exit 0
