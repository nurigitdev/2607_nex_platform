#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_nonproduction_path_inventory.v1"
PLAN_PATH = "docs/48_platform_production_readiness_plan.md"


@dataclass(frozen=True)
class EvidenceAnchor:
    path: str
    token: str


@dataclass(frozen=True)
class NonproductionPath:
    path_id: str
    path_class: str
    owners: tuple[str, ...]
    allowed_scope: tuple[str, ...]
    transition_targets: tuple[str, ...]
    evidence: tuple[EvidenceAnchor, ...]
    production_disposition: str = "FORBIDDEN_IN_PRODUCTION"


PATH_REGISTRY = (
    NonproductionPath(
        "local_mock_profile_default",
        "mock",
        ("platform_integration",),
        ("local", "regression"),
        ("S142",),
        (
            EvidenceAnchor(
                "services/_shared/nex_runtime/runtime_profiles.py",
                'or "local_mock").strip()',
            ),
            EvidenceAnchor(".env.example", "NEX_PROFILE=local_mock"),
        ),
    ),
    NonproductionPath(
        "memory_persistence",
        "memory",
        ("OA", "AE", "CX", "MO", "AG"),
        ("local", "unit_regression"),
        ("S142", "S145"),
        (
            EvidenceAnchor(
                "services/_shared/nex_runtime/persistence.py",
                'PERSISTENCE_MODE_MEMORY = "memory"',
            ),
            EvidenceAnchor(".env.example", "NEX_PERSISTENCE_MODE=memory"),
        ),
    ),
    NonproductionPath(
        "mock_model_provider",
        "mock",
        ("MO",),
        ("local", "regression"),
        ("S147",),
        (
            EvidenceAnchor(
                "services/_shared/nex_runtime/runtime_profiles.py",
                '"local_mock": RuntimeModes("memory", "mock", "test_mock", "memory")',
            ),
            EvidenceAnchor(".env.example", "NEX_MO_PROVIDER_MODE=mock"),
        ),
    ),
    NonproductionPath(
        "test_mock_service_trust",
        "test_only",
        ("OA", "platform_integration"),
        ("local", "compatibility_test"),
        ("S144",),
        (
            EvidenceAnchor(
                "services/_shared/nex_runtime/service_token_admission.py",
                'env.get("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "TEST_MOCK")',
            ),
            EvidenceAnchor(
                ".env.example", "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE=TEST_MOCK"
            ),
        ),
    ),
    NonproductionPath(
        "ae_mock_auth_session",
        "mock",
        ("AE", "OA"),
        ("local", "browser_regression"),
        ("S144",),
        (
            EvidenceAnchor(
                "services/_shared/nex_runtime/runtime_profiles.py",
                'AE_AUTH_SESSION_MODE_ENV: "mock" if profile == "local_mock" else "oa"',
            ),
        ),
    ),
    NonproductionPath(
        "local_private_filesystem",
        "local_filesystem",
        ("CX", "AE"),
        ("local", "test", "staging_rollback"),
        ("S146",),
        (
            EvidenceAnchor(
                "services/nex-cx/nex_cx/private_text_store.py",
                "/data/nex-platform/cx/private-text",
            ),
            EvidenceAnchor(
                "services/nex-ae-api/nex_ae_api/generated_response_storage.py",
                'GENERATED_RESPONSE_STORAGE_ENV = "NEX_AE_CHAT_RESPONSE_STORAGE_ROOT"',
            ),
        ),
    ),
    NonproductionPath(
        "local_model_filesystem",
        "local_filesystem",
        ("MO",),
        ("local_provider_development",),
        ("S147",),
        (
            EvidenceAnchor(
                "services/nex-mo/nex_mo/provider_catalog.py",
                'DEFAULT_MODEL_ROOT = "/data/nex-platform/models"',
            ),
        ),
    ),
    NonproductionPath(
        "test_database_profile",
        "test_only",
        ("OA", "AE", "CX", "MO", "AG"),
        ("protected_test",),
        ("S145", "S149"),
        (
            EvidenceAnchor(
                "services/_shared/nex_runtime/runtime_profiles.py",
                'name.replace("_DATABASE_URL", "_TEST_DATABASE_URL")',
            ),
        ),
    ),
    NonproductionPath(
        "protected_opt_in_smoke",
        "protected_opt_in",
        ("platform_integration",),
        ("protected_test", "staging_evidence"),
        ("S149",),
        (
            EvidenceAnchor(
                ".env.example", "NEX_PROTECTED_REMOTE_PROVIDER_LIVE_SMOKE=0"
            ),
            EvidenceAnchor(
                "scripts/smoke/run_platform_release_candidate_assurance.py",
                'skip_reason": f"{ENABLE_ENV} is not enabled."',
            ),
        ),
    ),
)


def run_platform_nonproduction_path_inventory(
    root: Path = ROOT,
) -> dict[str, Any]:
    plan = _read_text(root / PLAN_PATH)
    evidence_checks = {
        item.path_id: {
            anchor.path: anchor.token in _read_text(root / anchor.path)
            for anchor in item.evidence
        }
        for item in PATH_REGISTRY
    }
    record_checks = {
        item.path_id: {
            "evidence_present": all(evidence_checks[item.path_id].values()),
            "documented": f"`{item.path_id}`" in plan,
            "owners_present": bool(item.owners),
            "scope_present": bool(item.allowed_scope),
            "transition_target_present": bool(item.transition_targets),
            "production_forbidden": (
                item.production_disposition == "FORBIDDEN_IN_PRODUCTION"
            ),
        }
        for item in PATH_REGISTRY
    }
    path_ids = tuple(item.path_id for item in PATH_REGISTRY)
    checks = {
        "nine_unique_path_classes": len(path_ids) == len(set(path_ids)) == 9,
        "all_evidence_anchors_present": all(
            values["evidence_present"] for values in record_checks.values()
        ),
        "all_records_documented": all(
            values["documented"] for values in record_checks.values()
        ),
        "all_records_owned_and_scoped": all(
            values["owners_present"]
            and values["scope_present"]
            and values["transition_target_present"]
            for values in record_checks.values()
        ),
        "production_fallback_forbidden": all(
            values["production_forbidden"] for values in record_checks.values()
        ),
        "production_profile_is_nonmock": all(
            token in _read_text(
                root / "services/_shared/nex_runtime/runtime_profiles.py"
            )
            for token in (
                '"production": RuntimeModes("postgres", "live", "signed", "api")',
                'protected=selected != "local_mock"',
            )
        ),
    }
    issues = [name for name, passed in checks.items() if not passed]
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1404",
        "requirement": "S141",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": issues,
        "records": [
            {
                "path_id": item.path_id,
                "path_class": item.path_class,
                "owners": list(item.owners),
                "allowed_scope": list(item.allowed_scope),
                "production_disposition": item.production_disposition,
                "transition_targets": list(item.transition_targets),
                "checks": record_checks[item.path_id],
                "evidence": evidence_checks[item.path_id],
            }
            for item in PATH_REGISTRY
        ],
        "summary": {
            "path_count": len(PATH_REGISTRY),
            "evidence_anchor_count": sum(
                len(item.evidence) for item in PATH_REGISTRY
            ),
            "path_class_count": len({item.path_class for item in PATH_REGISTRY}),
            "production_forbidden_count": sum(
                item.production_disposition == "FORBIDDEN_IN_PRODUCTION"
                for item in PATH_REGISTRY
            ),
            "transition_requirement_count": len(
                {
                    target
                    for item in PATH_REGISTRY
                    for target in item.transition_targets
                }
            ),
        },
        "decision": {
            "retain_nonproduction_regression_paths": True,
            "silent_production_fallback_allowed": False,
            "production_connection_required": False,
            "next_slice": "1405" if passed else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "platform_nonproduction_path_inventory=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_nonproduction_path_inventory=pass "
        f"paths={summary.get('path_count', 0)} "
        f"anchors={summary.get('evidence_anchor_count', 0)} "
        f"classes={summary.get('path_class_count', 0)} "
        f"forbidden={summary.get('production_forbidden_count', 0)} "
        f"targets={summary.get('transition_requirement_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_nonproduction_path_inventory()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
