#!/usr/bin/env bash
# WSL Ubuntu wrapper for aigc-mark-toolkit
# Usage: ./run-local-skill.sh quick-clean /path/to/image.png
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLI_ROOT="$REPO_ROOT/cli"

export PYTHONPATH="$CLI_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONHASHSEED="0"

exec python3 -m aigc_mark_toolkit.cli "$@"
