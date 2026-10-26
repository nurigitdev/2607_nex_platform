#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services/_shared", ROOT / "scripts/smoke"):
    sys.path.insert(0, str(path))

from nex_runtime import load_env_file
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_p8_demo_s10b_installed_runtime import (
    run_p8_demo_s10b_installed_runtime,
)

SCHEMA_VERSION = "p8_demo_s10c_installed_result_closure.v1"
SMOKE_ENV = "NEX_P8_DEMO_S10C_LIVE"
DEFAULT_REPORT = ROOT / "reports/deployment/p8-demo-s10c-installed-result-closure.json"


def run_p8_demo_s10c_installed_result_closure(
    environ: Mapping[str, str], *, execute: bool
) -> dict[str, Any]:
    if not execute or environ.get(SMOKE_ENV) != "1":
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"--execute and {SMOKE_ENV}=1 are required",
        }
    delegated_environment = {**environ, "NEX_P8_DEMO_S10B_LIVE": "1"}
    inherited = run_p8_demo_s10b_installed_runtime(
        delegated_environment,
        execute=True,
    )
    projection = dict(inherited.get("projection") or {})
    resume_cycle = dict(inherited.get("resume_cycle") or {})
    replay_cycle = dict(inherited.get("replay_cycle") or {})
    checks = {
        "installed_runtime_passed": inherited.get("status") == "PASS",
        "result_verify_finalized": (
            resume_cycle.get("result_closure", {}).get("finalized_count") == 1
        ),
        "workspace_publication_acknowledged": (
            resume_cycle.get("result_closure", {}).get("published_count") == 1
            and projection.get("acknowledged_delivery_count") == 1
        ),
        "owner_workspace_activity_created_once": (
            projection.get("workspace_result_activity_count") == 1
        ),
        "agent_result_created_once": projection.get("agent_result_count") == 1,
        "voucher_committed_once": (
            projection.get("voucher_count") == 1
            and projection.get("voucher_line_count") == 2
            and projection.get("business_operation_count") == 1
        ),
        "restart_replay_zero_mutation": (
            replay_cycle.get("execution_count") == 0
            and replay_cycle.get("result_closure", {}).get("candidate_count") == 0
        ),
        "terminal_execution_succeeded": (
            projection.get("execution_state") == "SUCCEEDED"
            and projection.get("execution_phase") == "FINALIZE"
        ),
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "slice": "P8-DEMO-S10C",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "actual_postgres": bool(inherited.get("actual_postgres")),
        "signed_service_tokens": bool(inherited.get("signed_service_tokens")),
        "composition_mode": "EXISTING_COMPONENT_COMPOSITION",
        "migration_added": False,
        "storage_reuse": [
            "ae_agent_result",
            "ae_result_delivery",
            "ae_workspace_activities",
        ],
        "projection": projection,
        "resume_cycle": resume_cycle,
        "replay_cycle": replay_cycle,
        "checks": checks,
        "checks_passed": sum(bool(value) for value in checks.values()),
        "checks_total": len(checks),
        "secret_included": False,
    }
    return {**payload, "evidence_hash": semantic_sha256_hash_ref(payload)}


def summary_line(value: Mapping[str, Any]) -> str:
    checks = value.get("checks") or {}
    return (
        "p8_demo_s10c_installed_result_closure="
        f"{str(value.get('status', 'FAIL')).lower()} "
        f"postgres={str(bool(value.get('actual_postgres'))).lower()} "
        f"checks={sum(bool(item) for item in checks.values())}/{len(checks)}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    result = run_p8_demo_s10c_installed_result_closure(
        os.environ,
        execute=args.execute,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
