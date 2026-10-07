#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UV_BIN="${UV_BIN:-uv}"
UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/nex-platform-uv-cache}"

cd "$ROOT"
exec "$UV_BIN" pip compile requirements.txt \
  --python-version 3.12 \
  --python-platform x86_64-manylinux_2_28 \
  --generate-hashes \
  --no-annotate \
  --custom-compile-command "scripts/deployment/compile_python_lock.sh" \
  --cache-dir "$UV_CACHE_DIR" \
  --output-file deployment/locks/python-production.lock

