#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
AE_PATH = ROOT / "services" / "nex-ae-api"
sys.path.insert(0, str(AE_PATH))

from nex_ae_api.mvp_acceptance import (  # noqa: E402
    build_ae_mvp_acceptance_policy,
)
from nex_ae_api.mvp_acceptance_evaluation import (  # noqa: E402
    evaluate_ae_mvp_acceptance,
)
from nex_ae_api.mvp_operations_handoff import (  # noqa: E402
    build_ae_mvp_operations_handoff_candidate,
    verify_ae_mvp_operations_handoff,
)


SCHEMA_VERSION = "ae_mvp_acceptance_privacy_runbook.v1"
SLICE_ID = "1100"
OBSERVED_AT = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
EVIDENCE_HOOK = "run_ae_mvp_acceptance_privacy_runbook_evidence.py"
REQUIRED_DOCS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1092", "ae_mvp_acceptance_operations_boundary_audit"),
        ("1093", "ae_mvp_acceptance_policy"),
        ("1094", "ae_mvp_evidence_inventory"),
        ("1095", "ae_mvp_acceptance_evaluator"),
        ("1096", "ae_mvp_acceptance_api"),
        ("1097", "ae_mvp_acceptance_contract_hardening"),
        ("1098", "ae_mvp_operations_handoff"),
        ("1099", "ae_mvp_acceptance_postgres_live_smoke"),
    )
)
FORBIDDEN_KEYS = {
    "authorization",
    "credential",
    "database_url",
    "details",
    "message",
    "password",
    "prompt",
    "raw_document",
    "raw_payload",
    "response_text",
    "secret",
}


def run_ae_mvp_acceptance_privacy_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    policy = build_ae_mvp_acceptance_policy({})
    baseline = _passing_evidence()
    accepted = evaluate_ae_mvp_acceptance(
        baseline,
        policy=policy,
        now=OBSERVED_AT,
    )
    failures = _failure_matrix(baseline, policy=policy)
    runbooks = _runbooks()
    required_docs = [
        {"path": path, "present": (root / path).is_file()}
        for path in REQUIRED_DOCS
    ]
    quality_hook = EVIDENCE_HOOK in _read_text(root / QUALITY_GATE_PATH)
    candidate = build_ae_mvp_operations_handoff_candidate(
        generated_at=OBSERVED_AT
    )
    handoff = verify_ae_mvp_operations_handoff(candidate)
    projected = {
        "acceptance": {
            "status": accepted.get("status"),
            "operations_status": accepted.get("operations_status"),
            "passed_gate_count": _mapping(accepted.get("summary")).get(
                "passed_gate_count"
            ),
        },
        "failure_matrix": failures,
        "runbooks": runbooks,
        "handoff": {
            "status": handoff.get("status"),
            "target_service": candidate.get("target_service"),
            "manifest_status": candidate.get("manifest_status"),
        },
    }
    forbidden_paths = _forbidden_key_paths(projected)
    expected_failures = {
        "evidence_missing",
        "evidence_stale",
        "regression_failure",
        "coverage_below_threshold",
        "wrong_database",
        "cleanup_residue",
        "provider_model_drift",
        "provider_failure",
        "browser_verification_failure",
        "runbook_inventory_failure",
        "handoff_invalid",
    }
    checks = {
        "baseline_acceptance_passed": (
            accepted.get("status") == "ACCEPTED"
            and accepted.get("operations_status") == "READY_FOR_OPERATIONS"
            and _mapping(accepted.get("summary")).get("passed_gate_count") == 9
        ),
        "failure_matrix_complete": (
            set(failures) == expected_failures
            and all(item.get("status") == "BLOCKED" for item in failures.values())
        ),
        "runbook_inventory_complete": (
            len(runbooks) == 7
            and all(_runbook_complete(item) for item in runbooks.values())
        ),
        "required_docs_present": all(item["present"] for item in required_docs),
        "quality_gate_hook_present": quality_hook,
        "operations_handoff_verified": (
            handoff.get("status") == "VERIFIED"
            and candidate.get("target_service") == "nex-ag"
            and candidate.get("manifest_status") == "SEALED"
        ),
        "privacy_projection_safe": not forbidden_paths,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": SLICE_ID,
        "requirement": "S110",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "ae.mvp_acceptance.runbook_evidence_failed",
        "acceptance_projection": projected["acceptance"],
        "failure_matrix": failures,
        "runbook_inventory": runbooks,
        "required_documents": required_docs,
        "handoff_projection": projected["handoff"],
        "privacy": {
            "forbidden_key_paths": forbidden_paths,
            "raw_evidence_included": False,
        },
        "acceptance_gate_evidence": {
            "privacy_failure_runbooks": {
                "status": "PASS" if checks["runbook_inventory_complete"] else "FAIL",
                "observed_at": _timestamp(OBSERVED_AT),
                "runbook_count": len(runbooks),
            }
        },
        "checks": checks,
        "failed_checks": [name for name, value in checks.items() if not value],
    }


def _passing_evidence() -> dict[str, Any]:
    timestamp = _timestamp(OBSERVED_AT)
    return {
        "ae_requirement_closures": {
            "status": "PASS",
            "observed_at": timestamp,
            "requirement_count": 9,
            "issue_count": 0,
        },
        "contract_validation": {
            "status": "PASS",
            "observed_at": timestamp,
            "schema_count": 109,
            "example_count": 167,
            "negative_fixture_count": 131,
            "openapi_count": 7,
        },
        "unit_regression": {
            "status": "PASS",
            "observed_at": timestamp,
            "passed_tests": 8500,
            "failed_tests": 0,
        },
        "statement_coverage": {
            "status": "PASS",
            "observed_at": timestamp,
            "percent": 98.0,
        },
        "branch_coverage": {
            "status": "PASS",
            "observed_at": timestamp,
            "percent": 96.0,
        },
        "postgres_smoke": {
            "status": "PASS",
            "observed_at": timestamp,
            "backend": "postgresql",
            "databases": ["nex_ae_test", "nex_cx_test"],
            "zero_residue": True,
        },
        "live_grounded_generation": {
            "status": "PASS",
            "observed_at": timestamp,
            "provider_models": {
                "embedding": "Qwen3-Embedding-4B",
                "reranking": "Qwen3-Reranker-4B",
                "generation": "Qwen3.5-4B",
            },
            "failed_calls": 0,
            "browser_engine": "chromium",
            "display_state": "VERIFIED_RESPONSE",
            "server_secret_header": False,
        },
        "privacy_failure_runbooks": {
            "status": "PASS",
            "observed_at": timestamp,
            "runbook_count": 7,
        },
        "operations_handoff": {
            "status": "PASS",
            "observed_at": timestamp,
            "target_service": "nex-ag",
            "manifest_status": "SEALED",
        },
    }


def _failure_matrix(
    baseline: Mapping[str, Any], *, policy: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    cases: dict[str, tuple[str, Any]] = {
        "evidence_missing": ("postgres_smoke", None),
        "evidence_stale": (
            "postgres_smoke.observed_at",
            _timestamp(OBSERVED_AT - timedelta(hours=25)),
        ),
        "regression_failure": ("unit_regression.failed_tests", 1),
        "coverage_below_threshold": ("branch_coverage.percent", 95.99),
        "wrong_database": ("postgres_smoke.databases", ["nex_ae_dev", "nex_cx_test"]),
        "cleanup_residue": ("postgres_smoke.zero_residue", False),
        "provider_model_drift": (
            "live_grounded_generation.provider_models.reranking",
            "unexpected-model",
        ),
        "provider_failure": ("live_grounded_generation.failed_calls", 1),
        "browser_verification_failure": (
            "live_grounded_generation.display_state",
            "BLOCKED",
        ),
        "runbook_inventory_failure": ("privacy_failure_runbooks.runbook_count", 3),
        "handoff_invalid": ("operations_handoff.manifest_status", "OPEN"),
    }
    result: dict[str, dict[str, Any]] = {}
    for name, (path, value) in cases.items():
        mutated = deepcopy(baseline)
        _set_path(mutated, path, value)
        report = evaluate_ae_mvp_acceptance(
            mutated,
            policy=policy,
            now=OBSERVED_AT,
        )
        result[name] = {
            "status": report["status"],
            "blocked_gate_count": report["summary"]["blocked_gate_count"],
            "blocked_gate_ids": [item["gate_id"] for item in report["blockers"]],
        }
    return result


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cursor = target
    for part in parts[:-1]:
        cursor = cursor[part]
    if value is None:
        cursor.pop(parts[-1], None)
    else:
        cursor[parts[-1]] = value


def _runbooks() -> dict[str, dict[str, str]]:
    return {
        "postgres_connectivity_or_migration": _runbook(
            "Block acceptance and confirm the two test database identities.",
            "Restore connectivity, rerun migrations, and repeat the protected smoke.",
        ),
        "provider_unavailable_or_model_drift": _runbook(
            "Block acceptance and compare all three observed model identifiers.",
            "Restore the configured provider profile and repeat preflight plus live smoke.",
        ),
        "browser_or_verified_response_failure": _runbook(
            "Keep the response hidden and retain only redacted stage diagnostics.",
            "Repair the failed lifecycle stage and repeat the Chromium smoke.",
        ),
        "regression_or_coverage_failure": _runbook(
            "Block acceptance at the failing test or coverage gate.",
            "Fix the regression, run Full Gate, and use only fresh coverage evidence.",
        ),
        "privacy_or_secret_exposure": _runbook(
            "Stop evidence publication and rotate any potentially exposed material.",
            "Remove private fields, verify redaction tests, and regenerate all evidence.",
        ),
        "cleanup_residue": _runbook(
            "Block the PostgreSQL gate and isolate the fixed protected-smoke owner.",
            "Delete only owned probe rows, confirm zero residue, and rerun the smoke.",
        ),
        "handoff_tamper_or_hash_mismatch": _runbook(
            "Reject the manifest or attestation and deny AG consumption.",
            "Rebuild from repository assets and bind only after final acceptance.",
        ),
    }


def _runbook(containment: str, recovery: str) -> dict[str, str]:
    return {
        "detect": "Inspect the blocked gate and bounded failure code.",
        "contain": containment,
        "recover": recovery,
        "verify": "Require a fresh PASS result and preserve only redacted projections.",
        "owner": "nex-ae-operations",
    }


def _runbook_complete(item: Any) -> bool:
    return isinstance(item, Mapping) and all(
        isinstance(item.get(field), str) and bool(item[field].strip())
        for field in ("detect", "contain", "recover", "verify", "owner")
    )


def _forbidden_key_paths(value: Any, prefix: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}"
            if str(key).lower() in FORBIDDEN_KEYS:
                paths.append(path)
            paths.extend(_forbidden_key_paths(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paths.extend(_forbidden_key_paths(item, f"{prefix}[{index}]"))
    return paths


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = _mapping(evidence.get("checks"))
    runbooks = _mapping(evidence.get("runbook_inventory"))
    failures = _mapping(evidence.get("failure_matrix"))
    return (
        "ae_mvp_acceptance_runbook="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"runbooks={len(runbooks)} failure_cases={len(failures)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate AE MVP privacy and failure recovery runbook evidence."
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ae_mvp_acceptance_privacy_runbook_evidence()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
