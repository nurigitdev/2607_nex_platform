#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from run_platform_production_transition_dependency_plan import (  # noqa: E402
    TRANSITION_REQUIREMENTS,
)


SCHEMA_VERSION = "platform_production_evidence_decision_contract.v1"
PLAN_PATH = "docs/48_platform_production_readiness_plan.md"
EVIDENCE_FIELDS = (
    "schema_version",
    "evidence_id",
    "requirement_id",
    "control_ids",
    "release_candidate_id",
    "environment_class",
    "execution_mode",
    "actual_execution",
    "started_at",
    "completed_at",
    "source_revision",
    "artifact_digests",
    "configuration_digest",
    "dependency_evidence_digests",
    "checks",
    "metrics",
    "privacy",
    "rollback",
    "residue",
    "evidence_digest",
)
FORBIDDEN_KEY_FRAGMENTS = (
    "secret",
    "password",
    "token",
    "api_key",
    "cookie",
    "authorization",
    "database_url",
    "provider_endpoint",
    "private_payload",
    "source_document",
    "prompt_content",
    "physical_storage_path",
    "signing_private_key",
)
SAFE_METADATA_SUFFIXES = ("_count", "_digest", "_hash", "_id", "_status")
FRESHNESS_CLASSES = {
    "BUILD_BOUND": None,
    "RELEASE_WINDOW_72H": 72,
    "GO_LIVE_WINDOW_24H": 24,
    "IMMEDIATE_PREFLIGHT_4H": 4,
}
ROLLBACK_FIELDS = (
    "plan_id",
    "owner",
    "trigger_conditions",
    "last_known_good_artifacts",
    "last_known_good_configuration",
    "data_migration_strategy",
    "drill_status",
    "recovery_metrics",
    "residue_counts",
)
GO_NO_GO_GATES = (
    "all_dependency_evidence_passed",
    "evidence_fresh",
    "artifact_configuration_digest_exact",
    "no_open_p0",
    "p1_waivers_valid",
    "privacy_clean",
    "rollback_drill_passed",
    "zero_residue",
    "approval_roles_complete",
    "production_deployment_separate",
)
DECISION_STATES = ("GO", "NO_GO")


def run_platform_production_evidence_decision_contract(
    root: Path = ROOT,
) -> dict[str, Any]:
    plan = _read_text(root / PLAN_PATH)
    requirement_ids = tuple(
        item.requirement_id for item in TRANSITION_REQUIREMENTS
    )
    documented = {
        "evidence_fields": all(f"`{name}`" in plan for name in EVIDENCE_FIELDS),
        "forbidden_fields": all(
            f"`{name}`" in plan for name in FORBIDDEN_KEY_FRAGMENTS
        ),
        "freshness_classes": all(
            f"`{name}`" in plan for name in FRESHNESS_CLASSES
        ),
        "rollback_fields": all(
            f"`{name}`" in plan for name in ROLLBACK_FIELDS
        ),
        "decision_gates": all(f"`{name}`" in plan for name in GO_NO_GO_GATES),
        "decision_states": all(f"`{name}`" in plan for name in DECISION_STATES),
    }
    sample = _safe_sample_evidence()
    checks = {
        "s142_through_s150_covered": requirement_ids
        == tuple(f"S{number}" for number in range(142, 151)),
        "twenty_evidence_fields_unique": len(EVIDENCE_FIELDS)
        == len(set(EVIDENCE_FIELDS))
        == 20,
        "thirteen_forbidden_categories_unique": len(FORBIDDEN_KEY_FRAGMENTS)
        == len(set(FORBIDDEN_KEY_FRAGMENTS))
        == 13,
        "four_freshness_classes_exact": FRESHNESS_CLASSES
        == {
            "BUILD_BOUND": None,
            "RELEASE_WINDOW_72H": 72,
            "GO_LIVE_WINDOW_24H": 24,
            "IMMEDIATE_PREFLIGHT_4H": 4,
        },
        "nine_rollback_fields_unique": len(ROLLBACK_FIELDS)
        == len(set(ROLLBACK_FIELDS))
        == 9,
        "ten_decision_gates_unique": len(GO_NO_GO_GATES)
        == len(set(GO_NO_GO_GATES))
        == 10,
        "decision_states_fail_closed": DECISION_STATES == ("GO", "NO_GO"),
        "safe_sample_is_metadata_only": not _forbidden_paths(sample),
        "all_contract_terms_documented": all(documented.values()),
        "implicit_deployment_forbidden": (
            "there is no implicit or\nconditional deployment state" in plan
        ),
    }
    issues = [name for name, passed in checks.items() if not passed]
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1410",
        "requirement": "S141",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": issues,
        "documented": documented,
        "contract": {
            "evidence_fields": list(EVIDENCE_FIELDS),
            "forbidden_key_fragments": list(FORBIDDEN_KEY_FRAGMENTS),
            "freshness_classes": dict(FRESHNESS_CLASSES),
            "rollback_fields": list(ROLLBACK_FIELDS),
            "go_no_go_gates": list(GO_NO_GO_GATES),
            "decision_states": list(DECISION_STATES),
        },
        "summary": {
            "requirement_count": len(requirement_ids),
            "evidence_field_count": len(EVIDENCE_FIELDS),
            "forbidden_category_count": len(FORBIDDEN_KEY_FRAGMENTS),
            "freshness_class_count": len(FRESHNESS_CLASSES),
            "rollback_field_count": len(ROLLBACK_FIELDS),
            "decision_gate_count": len(GO_NO_GO_GATES),
            "decision_state_count": len(DECISION_STATES),
        },
        "decision": {
            "raw_private_values_allowed": False,
            "stale_evidence_allowed": False,
            "conditional_go_allowed": False,
            "production_deployment_performed": False,
            "next_slice": "1411" if passed else "blocked",
        },
    }


def _safe_sample_evidence() -> dict[str, Any]:
    return {
        "schema_version": "production_evidence.v1",
        "evidence_id": "opaque-evidence-id",
        "requirement_id": "S149",
        "control_ids": ["database_recovery"],
        "release_candidate_id": "opaque-release-id",
        "environment_class": "staging",
        "execution_mode": "protected",
        "actual_execution": True,
        "started_at": "2026-01-01T00:00:00Z",
        "completed_at": "2026-01-01T00:01:00Z",
        "source_revision": "revision",
        "artifact_digests": ["sha256:artifact"],
        "configuration_digest": "sha256:configuration",
        "dependency_evidence_digests": ["sha256:dependency"],
        "checks": {"restore": True},
        "metrics": {"recovery_seconds": 60},
        "privacy": {"violation_count": 0},
        "rollback": {"plan_id": "opaque-plan-id", "drill_status": "PASS"},
        "residue": {"row_count": 0},
        "evidence_digest": "sha256:evidence",
    }


def _forbidden_paths(value: object, path: str = "$") -> tuple[str, ...]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}"
            if _sensitive_key(key):
                findings.append(child_path)
            findings.extend(_forbidden_paths(child, child_path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            findings.extend(_forbidden_paths(child, f"{path}[{index}]"))
    return tuple(findings)


def _sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    if normalized.endswith(SAFE_METADATA_SUFFIXES):
        return False
    return any(fragment in normalized for fragment in FORBIDDEN_KEY_FRAGMENTS)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "platform_production_evidence_decision_contract=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_production_evidence_decision_contract=pass "
        f"requirements={summary.get('requirement_count', 0)} "
        f"fields={summary.get('evidence_field_count', 0)} "
        f"forbidden={summary.get('forbidden_category_count', 0)} "
        f"freshness={summary.get('freshness_class_count', 0)} "
        f"rollback={summary.get('rollback_field_count', 0)} "
        f"gates={summary.get('decision_gate_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_production_evidence_decision_contract()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
