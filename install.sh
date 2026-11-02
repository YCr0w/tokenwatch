#!/usr/bin/env bash
# tokwatch — auto-detects Claude Code / Codex / omp and installs into each.
# Thin wrapper; all logic is in install.py.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/install.py" "$@"
