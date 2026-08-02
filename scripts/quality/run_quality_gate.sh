#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-./.venv/bin/python}"
STATEMENT_COVERAGE_MIN="${STATEMENT_COVERAGE_MIN:-95}"
BRANCH_COVERAGE_MIN="${BRANCH_COVERAGE_MIN:-85}"
REPORT_DIR="${REPORT_DIR:-reports/coverage}"

export PYTHONPATH="services/_shared:services/nex-oa:services/nex-ag:services/nex-ae-api:services/nex-cx:services/nex-mo:scripts/dev:scripts/smoke:scripts/quality${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$REPORT_DIR"

"$PYTHON_BIN" -m pytest \
  --cov=services \
  --cov=scripts \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report="json:$REPORT_DIR/coverage.json" \
  "$@"

"$PYTHON_BIN" scripts/quality/check_coverage_thresholds.py \
  "$REPORT_DIR/coverage.json" \
  "$STATEMENT_COVERAGE_MIN" \
  "$BRANCH_COVERAGE_MIN"

"$PYTHON_BIN" scripts/quality/validate_contracts.py
