#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
SHARED_ROOT = ROOT / "services" / "_shared"
sys.path.insert(0, str(SHARED_ROOT))

from nex_runtime import evaluate_platform_trust_evidence


RUNBOOK = "docs/runbooks/platform_oa_backed_trust_operations.md"
CANONICAL = "docs/41_platform_oa_backed_trust_integration.md"
SMOKE_RUNNER = "scripts/smoke/run_platform_oa_backed_trust_postgres_smoke.py"
ACTIVE_SCHEMA = "contracts/schemas/common/active_service_claim.v1.schema.json"
LOGIN_SCHEMA = "contracts/schemas/service/nex_oa/user_login_response.v1.schema.json"
ACTIVE_EXAMPLE = "contracts/examples/auth/active_service_claim.cx.json"
LOGIN_EXAMPLE = "contracts/examples/auth/oa_user_login_response.active.json"
ACTIVE_NEGATIVE = "contracts/tests/negative/auth/active_service_claim.raw_token.json"
LOGIN_NEGATIVE = "contracts/tests/negative/auth/oa_user_login_response.password.json"
ACTIVE_OPENAPI = {
    "nex-ae-api": "contracts/openapi/nex-ae-api.openapi.yaml",
    "nex-cx": "contracts/openapi/nex-cx.openapi.yaml",
    "nex-mo": "contracts/openapi/nex-mo.openapi.yaml",
    "nex-ag": "contracts/openapi/nex-ag.openapi.yaml",
}


def run_platform_trust_operations_hardening(
    root: Path = ROOT,
) -> dict[str, Any]:
    examples_index = _read(root, "contracts/examples/index.json")
    negative_index = _read(root, "contracts/tests/negative/index.json")
    oa_openapi = _read(root, "contracts/openapi/nex-oa.openapi.yaml")
    runbook = _read(root, RUNBOOK)
    canonical = _read(root, CANONICAL)
    runner = _read(root, SMOKE_RUNNER)
    active_specs = {
        service_id: _read(root, path) for service_id, path in ACTIVE_OPENAPI.items()
    }
    checks = {
        "contract_files_present": all(
            (root / path).is_file()
            for path in (
                ACTIVE_SCHEMA,
                LOGIN_SCHEMA,
                ACTIVE_EXAMPLE,
                LOGIN_EXAMPLE,
                ACTIVE_NEGATIVE,
                LOGIN_NEGATIVE,
            )
        ),
        "examples_indexed": all(
            marker in examples_index
            for marker in (ACTIVE_EXAMPLE.removeprefix("contracts/"), LOGIN_EXAMPLE.removeprefix("contracts/"))
        ),
        "negative_privacy_fixtures_indexed": all(
            marker in negative_index
            for marker in (ACTIVE_NEGATIVE.removeprefix("contracts/"), LOGIN_NEGATIVE.removeprefix("contracts/"))
        ),
        "oa_signed_login_contract": all(
            marker in oa_openapi
            for marker in (
                "/internal/v1/auth/user-login:",
                "x-nex-route-class: CREDENTIAL",
                "OaUserLoginResponse",
                LOGIN_SCHEMA.removeprefix("contracts/"),
            )
        ),
        "active_claim_contracts_complete": all(
            all(
                marker in source
                for marker in (
                    "/internal/v1/auth/service-claim/active:",
                    "x-nex-required-scopes: [service:call]",
                    "x-nex-route-class: CREDENTIAL",
                    ACTIVE_SCHEMA.removeprefix("contracts/"),
                )
            )
            for source in active_specs.values()
        ),
        "cleanup_finalizer_frozen": all(
            marker in runner
            for marker in (
                "finally:",
                "_stop_processes(processes)",
                "_cleanup_oa(",
                "shutil.rmtree(work_root, ignore_errors=True)",
            )
        ),
        "runbook_complete": all(
            marker in runbook
            for marker in (
                "## Preconditions",
                "## Protected Command",
                "## Expected Evidence",
                "## Failure Triage",
                "## Cleanup Verification",
                "## Rollback And Fail-Closed",
                "## Secret Handling",
                "## Remote Provider Boundary",
            )
        ),
        "runbook_has_no_embedded_connection_or_secret": not any(
            marker in runbook.lower()
            for marker in (
                "postgresql+psycopg://",
                "postgresql://",
                "nuri1004",
                "ed6@c496em",
                "begin private key",
            )
        ),
        "privacy_evaluator_rejects_secret_keys": _privacy_probe_rejected(),
        "canonical_records_1339_and_1340": all(
            marker in canonical
            for marker in (
                "## Slice 1339 Protected Evidence",
                "Slice 1340 owns contract, privacy",
            )
        ),
        "remote_provider_boundary_explicit": (
            "outside S134" in runbook and "remote_provider_required\": False" in runner
        ),
    }
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        "hardening_schema_version": "platform_trust_operations_hardening.v1",
        "status": "PASS" if not issues else "FAIL",
        "failure_code": None if not issues else "platform_trust_operations_hardening_failed",
        "checks": checks,
        "issues": issues,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "active_claim_service_count": len(active_specs),
            "contract_artifact_count": 6,
            "runbook_section_count": 8,
        },
        "slice": "1340",
        "requirement": "S134",
        "next_slice": "1341",
    }


def _privacy_probe_rejected() -> bool:
    result = evaluate_platform_trust_evidence(
        {"hops": [], "denials": [], "restart": {}, "databases": {}, "raw_token": "private"}
    )
    return (
        result["status"] == "FAIL"
        and result["checks"]["privacy_safe"] is False
        and result["privacy_violations"] == ["$.raw_token"]
    )


def _read(root: Path, relative_path: str) -> str:
    path = root / relative_path
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    if report.get("status") != "PASS":
        return (
            "platform_trust_operations_hardening=fail "
            f"issues={len(report.get('issues') or [])}"
        )
    return (
        "platform_trust_operations_hardening=pass "
        f"checks={summary.get('passed_check_count')}/{summary.get('check_count')} "
        f"services={summary.get('active_claim_service_count')} "
        f"contracts={summary.get('contract_artifact_count')} next=1341"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    report = run_platform_trust_operations_hardening()
    print(
        summary_line(report)
        if args.summary
        else json.dumps(report, indent=2, sort_keys=True)
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
