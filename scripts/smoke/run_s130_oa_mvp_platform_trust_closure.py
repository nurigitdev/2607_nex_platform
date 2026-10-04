#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "scripts/smoke", ROOT / "services/nex-oa"):
    sys.path.insert(0, str(path))

from nex_oa.mvp_acceptance import (  # noqa: E402
    evaluate_oa_mvp_acceptance_inputs,
)
import run_s130_oa_mvp_platform_trust_acceptance as acceptance  # noqa: E402


FULL_GATE_ENV = "NEX_S130_FULL_GATE_CONTEXT"
SCHEMA_VERSION = "s130_oa_mvp_platform_trust_closure.v1"
SLICE_RANGE = "1292-1301"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
CLOSURE_RUNNER = "run_s130_oa_mvp_platform_trust_closure.py"
REQUIRED_FILES = (
    "services/nex-oa/nex_oa/mvp_acceptance.py",
    "services/nex-oa/nex_oa/mvp_identity_restart_smoke.py",
    "services/nex-oa/nex_oa/mvp_key_rotation_smoke.py",
    "services/nex-oa/nex_oa/mvp_revocation_restart_smoke.py",
    "services/nex-oa/nex_oa/mvp_cross_service_trust_smoke.py",
    "scripts/smoke/run_s130_oa_mvp_platform_trust_acceptance.py",
    "scripts/smoke/run_s130_oa_mvp_platform_trust_closure.py",
    "tests/test_s130_oa_mvp_platform_trust_acceptance.py",
    "tests/test_s130_oa_mvp_platform_trust_closure.py",
    "docs/runbooks/oa_mvp_platform_trust_operations.md",
)
SLICE_DOCUMENTS = (
    "1292_oa_mvp_acceptance_platform_trust_boundary.md",
    "1293_oa_signed_token_failure_audit_hardening.md",
    "1294_oa_mvp_acceptance_policy_traceability.md",
    "1295_oa_identity_session_authorization_restart_smoke.md",
    "1296_oa_signing_key_rotation_restart_smoke.md",
    "1297_oa_revocation_introspection_restart_smoke.md",
    "1298_oa_cross_service_signed_only_trust_smoke.md",
    "1299_oa_mvp_acceptance_contract_privacy_runbook.md",
    "1300_s130_oa_mvp_platform_trust_acceptance.md",
    "1301_s130_oa_mvp_platform_trust_closure.md",
)
TOKEN_CHECKS = (
    (
        "closure_registered",
        QUALITY_GATE_PATH,
        CLOSURE_RUNNER,
    ),
    (
        "integrated_acceptance_registered",
        QUALITY_GATE_PATH,
        "run_s130_oa_mvp_platform_trust_acceptance.py",
    ),
    (
        "closure_indexed",
        "docs/README.md",
        "1301_s130_oa_mvp_platform_trust_closure.md",
    ),
    (
        "operations_runbook_registered",
        "docs/runbooks/oa_mvp_platform_trust_operations.md",
        "run_s130_oa_mvp_platform_trust_acceptance.py",
    ),
)


def run_s130_oa_mvp_platform_trust_closure(
    root: Path = ROOT,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(FULL_GATE_ENV) != "1":
        return {
            "closure_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{FULL_GATE_ENV} is not enabled.",
        }
    required_files = [
        {"path": path, "present": (root / path).is_file()}
        for path in REQUIRED_FILES
    ]
    required_files.extend(
        {
            "path": f"docs/slices/{name}",
            "present": (root / "docs/slices" / name).is_file(),
        }
        for name in SLICE_DOCUMENTS
    )
    token_checks = [
        {
            "name": name,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for name, path, token in TOKEN_CHECKS
    ]
    quality_text = _read_text(root / QUALITY_GATE_PATH)
    final_command = _last_command(quality_text)
    integrated = _safe_acceptance(
        {
            **env,
            acceptance.SMOKE_ENV: "1",
        }
    )
    gates = evaluate_oa_mvp_acceptance_inputs(
        {
            "repository": integrated.get("status") == "PASS",
            "postgres_restart": integrated.get("status") == "PASS",
            "key_rotation": integrated.get("status") == "PASS",
            "revocation": integrated.get("status") == "PASS",
            "cross_service": integrated.get("status") == "PASS",
            "failure_audit": integrated.get("status") == "PASS",
            "contracts_privacy": integrated.get("status") == "PASS",
            "full_gate": True,
        }
    )
    integrated_summary = _mapping(integrated.get("summary"))
    checks = {
        "required_files_present": all(
            item["present"] for item in required_files
        ),
        "required_tokens_present": all(
            item["present"] for item in token_checks
        ),
        "closure_is_final_quality_command": (
            CLOSURE_RUNNER in final_command and "--summary" in final_command
        ),
        "integrated_acceptance_passed": integrated.get("status") == "PASS",
        "actual_postgres_workflows_complete": (
            integrated_summary.get("actual_postgres_smoke_count") == 4
        ),
        "pre_full_gates_complete": (
            integrated_summary.get("passed_gate_count") == 7
            and integrated_summary.get("gate_count") == 8
        ),
        "cleanup_residue_zero": (
            integrated_summary.get("cleanup_residue_count") == 0
        ),
        "all_acceptance_gates_complete": (
            gates["status"] == "ACCEPTED"
            and gates["passed_gate_count"] == 8
            and not gates["failed_gates"]
            and not gates["missing_gates"]
            and not gates["unexpected_gates"]
        ),
        "deployment_boundary_preserved": (
            "Production activation still requires"
            in _read_text(
                root / "docs/runbooks/oa_mvp_platform_trust_operations.md"
            )
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1301",
        "slice_range": SLICE_RANGE,
        "requirement": "S130",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "s130_oa_mvp_platform_trust_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S131" if passed else "BLOCKED",
        "production_activation": (
            "DEPLOYMENT_CONTROLS_REQUIRED" if passed else "BLOCKED"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "gate_evaluation": gates,
        "integrated_acceptance_status": integrated.get("status"),
        "required_files": required_files,
        "token_checks": token_checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "required_file_count": len(required_files),
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "passed_gate_count": gates["passed_gate_count"],
            "gate_count": gates["gate_count"],
            "actual_postgres_smoke_count": int(
                integrated_summary.get("actual_postgres_smoke_count") or 0
            ),
            "cleanup_residue_count": int(
                integrated_summary.get("cleanup_residue_count") or 0
            ),
        },
        "decision": {
            "completed_scope": (
                "oa_fr_001_through_005_repository_and_contract_evidence",
                "actual_postgresql_identity_session_authorization_restart",
                "restart_safe_key_rotation_jwks_and_revocation",
                "ae_cx_mo_ag_signed_only_sensitive_route_trust",
                "privacy_failure_audit_runbook_and_full_gate",
            ),
            "production_kms_vault_pkcs11": "DEPLOYMENT_REQUIRED",
            "production_tls_secret_injection": "DEPLOYMENT_REQUIRED",
            "external_idp_registration": "DEPLOYMENT_REQUIRED",
            "remote_model_provider_required": False,
            "next_requirement": "S131",
        },
        "next_requirement": "S131" if passed else "blocked",
        "next_requirement_scope": "pending_user_review" if passed else "blocked",
    }


def _safe_acceptance(env: Mapping[str, str]) -> dict[str, Any]:
    try:
        return dict(
            acceptance.run_s130_oa_mvp_platform_trust_acceptance(env)
        )
    except Exception as exc:
        return {
            "status": "ERROR",
            "failure_code": "integrated_acceptance_execution_failed",
            "detail": exc.__class__.__name__,
        }


def _last_command(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"s130_oa_mvp_trust_closure=skip reason={FULL_GATE_ENV}"
    if evidence.get("status") != "PASS":
        return (
            "s130_oa_mvp_trust_closure=fail "
            f"code={evidence.get('failure_code')}"
        )
    summary = evidence.get("summary") or {}
    return (
        "s130_oa_mvp_trust_closure=pass "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"gates={summary.get('passed_gate_count', 0)}/"
        f"{summary.get('gate_count', 0)} "
        f"postgres={summary.get('actual_postgres_smoke_count', 0)} "
        f"residue={summary.get('cleanup_residue_count', 0)} "
        f"activation={evidence.get('production_activation', 'BLOCKED')} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s130_oa_mvp_platform_trust_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
