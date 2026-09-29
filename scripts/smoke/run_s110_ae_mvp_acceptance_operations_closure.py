#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "scripts" / "quality",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_ae_api.mvp_acceptance import (  # noqa: E402
    build_ae_mvp_acceptance_policy,
    build_ae_mvp_evidence_inventory,
)
from nex_ae_api.mvp_acceptance_evaluation import (  # noqa: E402
    evaluate_ae_mvp_acceptance,
)
from nex_ae_api.mvp_operations_handoff import (  # noqa: E402
    bind_ae_mvp_operations_handoff,
    build_ae_mvp_operations_handoff_candidate,
    verify_ae_mvp_operations_handoff,
    verify_ae_mvp_operations_handoff_attestation,
)
from run_ae_mvp_acceptance_operations_boundary_audit import (  # noqa: E402
    run_ae_mvp_acceptance_operations_boundary_audit as run_boundary,
)
from run_ae_mvp_acceptance_privacy_runbook_evidence import (  # noqa: E402
    run_ae_mvp_acceptance_privacy_runbook_evidence as run_runbook,
)
from validate_contracts import validate_contract_tree  # noqa: E402


SCHEMA_VERSION = "s110_ae_mvp_acceptance_operations_closure.v1"
SLICE_RANGE = "1092-1101"
FINAL_ENV = "NEX_AE_MVP_FINAL_ACCEPTANCE"
LIVE_EVIDENCE_ENV = "NEX_AE_MVP_LIVE_EVIDENCE_JSON"
COVERAGE_JSON_ENV = "NEX_AE_MVP_COVERAGE_JSON"
PYTEST_LOG_ENV = "NEX_AE_MVP_PYTEST_LOG"
PYTEST_RESULT_PATTERN = re.compile(r"(?P<passed>\d+) passed(?:, [^\n]+)? in ")
REQUIRED_FILES = (
    "services/nex-ae-api/nex_ae_api/mvp_acceptance.py",
    "services/nex-ae-api/nex_ae_api/mvp_acceptance_evaluation.py",
    "services/nex-ae-api/nex_ae_api/mvp_acceptance_api.py",
    "services/nex-ae-api/nex_ae_api/mvp_operations_handoff.py",
    "contracts/openapi/nex-ae-api.openapi.yaml",
    "contracts/schemas/service/nex_ae_api/mvp_acceptance.v1.schema.json",
    "scripts/smoke/run_ae_mvp_acceptance_operations_boundary_audit.py",
    "scripts/smoke/run_ae_mvp_acceptance_postgres_live_smoke.py",
    "scripts/smoke/run_ae_mvp_acceptance_privacy_runbook_evidence.py",
    "scripts/smoke/run_s110_ae_mvp_acceptance_operations_closure.py",
    "tests/test_s110_ae_mvp_acceptance_operations_closure.py",
    "docs/README.md",
    *(
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
            ("1100", "ae_mvp_acceptance_operator_runbook"),
            ("1101", "s110_ae_mvp_acceptance_operations_closure"),
        )
    ),
)
TOKEN_CHECKS = (
    ("policy", "services/nex-ae-api/nex_ae_api/mvp_acceptance.py", "def build_ae_mvp_acceptance_policy"),
    ("inventory", "services/nex-ae-api/nex_ae_api/mvp_acceptance.py", "def build_ae_mvp_evidence_inventory"),
    ("evaluator", "services/nex-ae-api/nex_ae_api/mvp_acceptance_evaluation.py", "def evaluate_ae_mvp_acceptance"),
    ("protected_api", "services/nex-ae-api/nex_ae_api/mvp_acceptance_api.py", "AE_MVP_ACCEPTANCE_OPERATIONS_PATH"),
    ("handoff", "services/nex-ae-api/nex_ae_api/mvp_operations_handoff.py", "def bind_ae_mvp_operations_handoff"),
    ("quality_live", "scripts/quality/run_quality_gate.sh", "run_ae_mvp_acceptance_postgres_live_smoke.py"),
    ("quality_runbook", "scripts/quality/run_quality_gate.sh", "run_ae_mvp_acceptance_privacy_runbook_evidence.py"),
    ("quality_closure", "scripts/quality/run_quality_gate.sh", "run_s110_ae_mvp_acceptance_operations_closure.py"),
    ("docs_index", "docs/README.md", "1101_s110_ae_mvp_acceptance_operations_closure.md"),
)


def run_s110_ae_mvp_acceptance_operations_closure(
    root: Path = ROOT,
    environ: Mapping[str, str] | None = None,
    *,
    live_evidence: Mapping[str, Any] | None = None,
    regression_evidence: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    observed_at = _normalize_now(now)
    final_requested = env.get(FINAL_ENV) == "1"
    required_files = [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_FILES
    ]
    token_checks = [
        {"name": name, "path": path, "present": token in _read_text(root / path)}
        for name, path, token in TOKEN_CHECKS
    ]
    boundary = _safe_evidence(lambda: run_boundary(root), "boundary_failed")
    inventory = _safe_evidence(
        lambda: build_ae_mvp_evidence_inventory(root), "inventory_failed"
    )
    contracts = _contract_evidence(root)
    runbook = _safe_evidence(lambda: run_runbook(root), "runbook_failed")
    candidate = _safe_evidence(
        lambda: build_ae_mvp_operations_handoff_candidate(
            generated_at=observed_at,
            root=root,
        ),
        "handoff_candidate_failed",
    )
    candidate_verification = verify_ae_mvp_operations_handoff(candidate)
    final = _final_evidence(
        env=env,
        final_requested=final_requested,
        inventory=inventory,
        contracts=contracts,
        runbook=runbook,
        candidate=candidate,
        live_evidence=live_evidence,
        regression_evidence=regression_evidence,
        observed_at=observed_at,
    )
    boundary_summary = _mapping(boundary.get("summary"))
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "boundary_audit_closed": (
            boundary.get("status") == "PASS"
            and boundary_summary.get("resolved_gap_count") == 8
            and boundary_summary.get("open_gap_count") == 0
            and boundary.get("next_slice") == "1101"
        ),
        "requirement_inventory_complete": (
            inventory.get("status") == "PASS"
            and _mapping(inventory.get("scope")).get("included_requirement_count") == 9
        ),
        "contracts_valid": contracts.get("status") == "PASS",
        "privacy_runbook_passed": (
            runbook.get("status") == "PASS"
            and len(_mapping(runbook.get("runbook_inventory"))) >= 4
        ),
        "operations_candidate_verified": (
            candidate_verification.get("status") == "VERIFIED"
            and candidate.get("manifest_status") == "SEALED"
            and candidate.get("target_service") == "nex-ag"
        ),
        "final_evidence_policy_satisfied": (
            not final_requested
            or (
                final.get("status") == "PASS"
                and final.get("acceptance_status") == "ACCEPTED"
                and final.get("operations_status") == "READY_FOR_OPERATIONS"
                and final.get("passed_gate_count") == 9
                and final.get("attestation_status") == "BOUND"
                and final.get("attestation_verification") == "VERIFIED"
            )
        ),
        "raw_evidence_absent": final.get("raw_evidence_exposed") is False,
    }
    passed = all(checks.values())
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1101",
        "slice_range": SLICE_RANGE,
        "requirement": "S110",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "s110_ae_mvp_acceptance_operations_closure_failed",
        "closure_readiness": (
            "AE_MVP_ACCEPTED_OPERATIONS_HANDOFF_BOUND"
            if passed and final_requested
            else "REPOSITORY_READY_FINAL_EVIDENCE_PENDING" if passed else "BLOCKED"
        ),
        "final_acceptance_requested": final_requested,
        "production_release_approved": False,
        "new_tables": [],
        "new_indexes": [],
        "checks": checks,
        "failed_checks": [name for name, value in checks.items() if not value],
        "summary": {
            "required_file_count": len(required_files),
            "missing_file_count": sum(not item["present"] for item in required_files),
            "token_count": len(token_checks),
            "missing_token_count": sum(not item["present"] for item in token_checks),
            "resolved_gap_count": int(boundary_summary.get("resolved_gap_count") or 0),
            "requirement_count": int(_mapping(inventory.get("scope")).get("included_requirement_count") or 0),
            "contract_schema_count": int(contracts.get("schema_count") or 0),
            "runbook_count": len(_mapping(runbook.get("runbook_inventory"))),
        },
        "final_evidence": final,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S111",
        "next_requirement_scope": "to_be_confirmed",
        "deferred_scope": [
            "product_wide_release_approval",
            "production_deployment_certification",
            "production_identity_provider_activation",
            "production_object_storage_activation",
            "distributed_load_and_disaster_recovery_certification",
        ],
    }


def _final_evidence(
    *,
    env: Mapping[str, str],
    final_requested: bool,
    inventory: Mapping[str, Any],
    contracts: Mapping[str, Any],
    runbook: Mapping[str, Any],
    candidate: Mapping[str, Any],
    live_evidence: Mapping[str, Any] | None,
    regression_evidence: Mapping[str, Any] | None,
    observed_at: datetime,
) -> dict[str, Any]:
    if not final_requested:
        return {
            "status": "PENDING",
            "acceptance_status": "PENDING",
            "operations_status": "PENDING",
            "attestation_status": None,
            "attestation_verification": None,
            "raw_evidence_exposed": False,
        }
    try:
        live = dict(live_evidence) if live_evidence is not None else _load_json_evidence(
            env.get(LIVE_EVIDENCE_ENV), label="live evidence", now=observed_at
        )
        regression = (
            dict(regression_evidence)
            if regression_evidence is not None
            else _load_regression_evidence(
                env.get(COVERAGE_JSON_ENV),
                env.get(PYTEST_LOG_ENV),
                now=observed_at,
            )
        )
        gates = _acceptance_gate_evidence(
            inventory=inventory,
            contracts=contracts,
            runbook=runbook,
            live=live,
            regression=regression,
            observed_at=observed_at,
        )
        policy = build_ae_mvp_acceptance_policy({})
        report = evaluate_ae_mvp_acceptance(gates, policy=policy, now=observed_at)
        attestation: Mapping[str, Any] = {}
        verification: Mapping[str, Any] = {}
        if report.get("status") == "ACCEPTED":
            attestation = bind_ae_mvp_operations_handoff(
                candidate,
                report,
                bound_at=observed_at,
            )
            verification = verify_ae_mvp_operations_handoff_attestation(
                attestation,
                candidate=candidate,
                acceptance_report=report,
            )
        return {
            "status": "PASS" if report.get("status") == "ACCEPTED" else "FAIL",
            "acceptance_status": report.get("status"),
            "operations_status": report.get("operations_status"),
            "passed_gate_count": _mapping(report.get("summary")).get("passed_gate_count"),
            "blocked_gate_count": _mapping(report.get("summary")).get("blocked_gate_count"),
            "acceptance_id": report.get("acceptance_id"),
            "attestation_status": attestation.get("attestation_status"),
            "attestation_verification": verification.get("status"),
            "manifest_status": candidate.get("manifest_status"),
            "regression": regression,
            "live_gate_statuses": {
                name: _mapping(gates.get(name)).get("status")
                for name in ("postgres_smoke", "live_grounded_generation")
            },
            "raw_evidence_exposed": False,
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "FAIL",
            "failure_code": "final_evidence_invalid",
            "error_type": exc.__class__.__name__,
            "acceptance_status": "BLOCKED",
            "operations_status": "BLOCKED",
            "attestation_status": None,
            "attestation_verification": None,
            "raw_evidence_exposed": False,
        }


def _acceptance_gate_evidence(
    *,
    inventory: Mapping[str, Any],
    contracts: Mapping[str, Any],
    runbook: Mapping[str, Any],
    live: Mapping[str, Any],
    regression: Mapping[str, Any],
    observed_at: datetime,
) -> dict[str, Any]:
    timestamp = _timestamp(observed_at)
    live_gates = _mapping(live.get("acceptance_gate_evidence"))
    runbook_gate = _mapping(runbook.get("acceptance_gate_evidence"))
    return {
        "ae_requirement_closures": {
            "status": inventory.get("status"),
            "observed_at": timestamp,
            "requirement_count": _mapping(inventory.get("scope")).get("included_requirement_count"),
            "issue_count": len(inventory.get("issues") or []),
        },
        "contract_validation": {
            "status": contracts.get("status"),
            "observed_at": timestamp,
            "schema_count": contracts.get("schema_count"),
            "example_count": contracts.get("example_count"),
            "negative_fixture_count": contracts.get("negative_fixture_count"),
            "openapi_count": contracts.get("openapi_count"),
        },
        "unit_regression": {
            "status": "PASS" if regression.get("failed_tests") == 0 else "FAIL",
            "observed_at": timestamp,
            "passed_tests": regression.get("passed_tests"),
            "failed_tests": regression.get("failed_tests"),
        },
        "statement_coverage": {
            "status": "PASS",
            "observed_at": timestamp,
            "percent": regression.get("statement_percent"),
        },
        "branch_coverage": {
            "status": "PASS",
            "observed_at": timestamp,
            "percent": regression.get("branch_percent"),
        },
        "postgres_smoke": dict(_mapping(live_gates.get("postgres_smoke"))),
        "live_grounded_generation": dict(_mapping(live_gates.get("live_grounded_generation"))),
        "privacy_failure_runbooks": {
            **dict(_mapping(runbook_gate.get("privacy_failure_runbooks"))),
            "observed_at": timestamp,
        },
        "operations_handoff": dict(_mapping(live_gates.get("operations_handoff"))),
    }


def _load_json_evidence(path_value: Any, *, label: str, now: datetime) -> dict[str, Any]:
    path = Path(str(path_value or ""))
    if not path.is_file():
        raise ValueError(f"{label} file is missing")
    if now - datetime.fromtimestamp(path.stat().st_mtime, tz=UTC) > timedelta(hours=24):
        raise ValueError(f"{label} file is stale")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("status") != "PASS":
        raise ValueError(f"{label} does not prove PASS")
    return value


def _load_regression_evidence(
    coverage_path_value: Any,
    pytest_log_path_value: Any,
    *,
    now: datetime,
) -> dict[str, Any]:
    coverage_path = Path(str(coverage_path_value or ""))
    pytest_log_path = Path(str(pytest_log_path_value or ""))
    for path in (coverage_path, pytest_log_path):
        if not path.is_file():
            raise ValueError("regression evidence file is missing")
        if now - datetime.fromtimestamp(path.stat().st_mtime, tz=UTC) > timedelta(hours=24):
            raise ValueError("regression evidence file is stale")
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    totals = _mapping(coverage.get("totals"))
    statement = totals.get("percent_statements_covered")
    branch = totals.get("percent_branches_covered")
    if not _valid_percent(statement) or not _valid_percent(branch):
        raise ValueError("coverage percentages are invalid")
    log = pytest_log_path.read_text(encoding="utf-8")
    matches = list(PYTEST_RESULT_PATTERN.finditer(log))
    if not matches or re.search(r"\b\d+ failed\b", log):
        raise ValueError("pytest log does not prove a passing Full Gate")
    return {
        "passed_tests": int(matches[-1].group("passed")),
        "failed_tests": 0,
        "statement_percent": float(statement),
        "branch_percent": float(branch),
    }


def _contract_evidence(root: Path) -> dict[str, Any]:
    try:
        result = validate_contract_tree(root / "contracts")
    except Exception as exc:
        return {"status": "FAIL", "error_type": exc.__class__.__name__}
    return {
        "status": "PASS" if result.ok else "FAIL",
        "schema_count": result.schema_count,
        "example_count": result.example_count,
        "negative_fixture_count": result.negative_example_count,
        "openapi_count": result.openapi_count,
    }


def _safe_evidence(
    builder: Callable[[], Mapping[str, Any]], failure_code: str
) -> dict[str, Any]:
    try:
        return dict(builder())
    except Exception as exc:
        return {"status": "FAIL", "failure_code": failure_code, "error_type": exc.__class__.__name__}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _valid_percent(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100


def _normalize_now(value: datetime | None) -> datetime:
    normalized = datetime.now(UTC) if value is None else value
    if normalized.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return normalized.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    final = _mapping(evidence.get("final_evidence"))
    return (
        "s110_ae_mvp_acceptance_operations_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"gaps={summary.get('resolved_gap_count', 0)}/8 "
        f"requirements={summary.get('requirement_count', 0)}/9 "
        f"acceptance={final.get('acceptance_status', 'PENDING')} "
        f"handoff={final.get('attestation_status') or 'PENDING'} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Close S110 AE MVP acceptance and operations handoff.")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    evidence = run_s110_ae_mvp_acceptance_operations_closure()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
