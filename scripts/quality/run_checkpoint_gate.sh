#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-./.venv/bin/python}"
EXECUTION_MODE="${NEX_QUALITY_GATE_EXECUTION:-serial}"

case "$EXECUTION_MODE" in
  serial)
    exec "$PYTHON_BIN" scripts/quality/run_tiered_quality_gate.py checkpoint "$@"
    ;;
  parallel)
    exec "$PYTHON_BIN" scripts/quality/run_parallel_quality_gate.py checkpoint "$@"
    ;;
  *)
    echo "checkpoint gate configuration error: NEX_QUALITY_GATE_EXECUTION must be serial or parallel" >&2
    exit 2
    ;;
esac
