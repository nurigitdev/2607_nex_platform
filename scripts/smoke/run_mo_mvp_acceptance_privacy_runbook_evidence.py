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
for path in (ROOT / "services" / "nex-mo", ROOT / "scripts" / "smoke"):
    sys.path.insert(0, str(path))

from nex_mo.mvp_acceptance import build_mo_mvp_acceptance_policy  # noqa: E402
from nex_mo.mvp_acceptance_evaluation import (  # noqa: E402
    evaluate_mo_mvp_acceptance,
)
from nex_mo.mvp_oa_transition_handoff import (  # noqa: E402
    build_mo_mvp_oa_transition_candidate,
    verify_mo_mvp_oa_transition_handoff,
)
from run_mo_mvp_acceptance_evaluator import (  # noqa: E402
    build_passing_evidence,
)


SCHEMA_VERSION = "mo_mvp_acceptance_privacy_runbook.v1"
SLICE_ID = "1200"
OBSERVED_AT = datetime(2026, 10, 1, 11, 0, tzinfo=UTC)
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
EVIDENCE_HOOK = "run_mo_mvp_acceptance_privacy_runbook_evidence.py"
REQUIRED_DOCS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("1192", "mo_mvp_acceptance_oa_transition_boundary_audit"),
        ("1193", "mo_mvp_acceptance_policy"),
        ("1194", "mo_mvp_evidence_inventory"),
        ("1195", "mo_mvp_acceptance_evaluator"),
        ("1196", "mo_mvp_acceptance_api"),
        ("1197", "mo_mvp_acceptance_contract_hardening"),
        ("1198", "mo_mvp_oa_transition_handoff"),
        ("1199", "mo_mvp_acceptance_postgres_live_smoke"),
        ("1200", "mo_mvp_acceptance_operator_runbook"),
    )
)
FORBIDDEN_KEYS = {
    "api_key",
    "authorization",
    "credential",
    "database_url",
    "details",
    "endpoint",
    "message",
    "password",
    "provider_payload",
    "raw_payload",
    "secret",
    "ssh_target",
}


def run_mo_mvp_acceptance_privacy_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    policy = build_mo_mvp_acceptance_policy({})
    baseline = build_passing_evidence()
    for item in baseline.values():
        item["observed_at"] = _timestamp(OBSERVED_AT)
    accepted = evaluate_mo_mvp_acceptance(
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
    candidate: dict[str, Any] = {}
    handoff: Mapping[str, Any] = {
        "status": "INVALID",
        "failure_code": "required_asset_missing",
    }
    try:
        candidate = build_mo_mvp_oa_transition_candidate(
            generated_at=OBSERVED_AT,
            root=root,
        )
        handoff = verify_mo_mvp_oa_transition_handoff(candidate)
    except Exception:
        pass

    projected = {
        "acceptance": {
            "status": accepted.get("status"),
            "transition_status": accepted.get("transition_status"),
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
        "capability_unavailable",
        "provider_failure",
        "bfloat16_mismatch",
        "runbook_inventory_failure",
        "handoff_invalid",
    }
    checks = {
        "baseline_acceptance_passed": (
            accepted.get("status") == "ACCEPTED"
            and accepted.get("transition_status") == "READY_FOR_OA"
            and _mapping(accepted.get("summary")).get("passed_gate_count") == 9
        ),
        "failure_matrix_complete": (
            set(failures) == expected_failures
            and all(item.get("status") == "BLOCKED" for item in failures.values())
            and all(
                item.get("blocked_gate_count") == 1 for item in failures.values()
            )
        ),
        "runbook_inventory_complete": (
            len(runbooks) == 7
            and all(_runbook_complete(item) for item in runbooks.values())
        ),
        "required_docs_present": all(item["present"] for item in required_docs),
        "quality_gate_hook_present": quality_hook,
        "oa_handoff_verified": (
            handoff.get("status") == "VERIFIED"
            and candidate.get("target_service") == "nex-oa"
            and candidate.get("manifest_status") == "SEALED"
        ),
        "privacy_projection_safe": not forbidden_paths,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": SLICE_ID,
        "requirement": "S120",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "mo.mvp_acceptance.runbook_evidence_failed"
        ),
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
                "status": (
                    "PASS" if checks["runbook_inventory_complete"] else "FAIL"
                ),
                "observed_at": _timestamp(OBSERVED_AT),
                "runbook_count": len(runbooks),
            }
        },
        "checks": checks,
        "failed_checks": [name for name, value in checks.items() if not value],
        "next_slice": "1201" if passed else "blocked",
    }


def _failure_matrix(
    baseline: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    cases: dict[str, tuple[str, Any]] = {
        "evidence_missing": ("postgres_smoke", None),
        "evidence_stale": (
            "postgres_smoke.observed_at",
            _timestamp(OBSERVED_AT - timedelta(hours=25)),
        ),
        "regression_failure": ("unit_regression.failed_tests", 1),
        "coverage_below_threshold": ("branch_coverage.percent", 95.99),
        "wrong_database": ("postgres_smoke.database", "nex_mo_dev"),
        "cleanup_residue": ("postgres_smoke.zero_residue", False),
        "provider_model_drift": (
            "live_provider_acceptance.provider_models.reranking",
            "unexpected-model",
        ),
        "capability_unavailable": (
            "live_provider_acceptance.ready_capabilities",
            2,
        ),
        "provider_failure": ("live_provider_acceptance.failed_calls", 1),
        "bfloat16_mismatch": (
            "live_provider_acceptance.explicit_bfloat16",
            False,
        ),
        "runbook_inventory_failure": ("privacy_failure_runbooks.runbook_count", 3),
        "handoff_invalid": ("oa_transition_handoff.manifest_status", "OPEN"),
    }
    result: dict[str, dict[str, Any]] = {}
    for name, (path, value) in cases.items():
        mutated = deepcopy(baseline)
        _set_path(mutated, path, value)
        report = evaluate_mo_mvp_acceptance(
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
            "Block acceptance and confirm the MO test database identity.",
            "Restore connectivity, rerun migrations, and repeat protected smoke.",
        ),
        "provider_unavailable_or_model_drift": _runbook(
            "Block acceptance and compare all three bounded model identifiers.",
            "Restore the catalog route and repeat preflight plus live smoke.",
        ),
        "runtime_precision_or_gpu_failure": _runbook(
            "Block acceptance when SSH, BF16, process, or GPU evidence is not healthy.",
            "Repair runtime launch settings and repeat protected observation.",
        ),
        "regression_or_coverage_failure": _runbook(
            "Block acceptance at the failing test or coverage gate.",
            "Fix the regression, run Full Gate, and use only fresh evidence.",
        ),
        "privacy_or_secret_exposure": _runbook(
            "Stop evidence publication and rotate potentially exposed material.",
            "Remove private fields, verify redaction, and regenerate evidence.",
        ),
        "cleanup_residue": _runbook(
            "Block PostgreSQL acceptance and isolate unique telemetry identities.",
            "Delete only probe-owned rows, confirm zero residue, and rerun.",
        ),
        "handoff_tamper_or_hash_mismatch": _runbook(
            "Reject the manifest or attestation and deny OA consumption.",
            "Rebuild from repository assets and bind only after final acceptance.",
        ),
    }


def _runbook(containment: str, recovery: str) -> dict[str, str]:
    return {
        "detect": "Inspect the blocked gate and bounded failure code.",
        "contain": containment,
        "recover": recovery,
        "verify": "Require a fresh PASS and preserve only redacted projections.",
        "owner": "nex-mo-operations",
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
        "mo_mvp_acceptance_runbook="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"runbooks={len(runbooks)} failure_cases={len(failures)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate MO MVP privacy and failure recovery runbook evidence."
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_mvp_acceptance_privacy_runbook_evidence()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
