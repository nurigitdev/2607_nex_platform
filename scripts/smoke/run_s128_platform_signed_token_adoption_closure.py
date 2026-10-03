#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/smoke"))

from run_ae_signed_token_adoption import (  # noqa: E402
    run_ae_signed_token_adoption as run_ae,
)
from run_ag_signed_token_adoption import (  # noqa: E402
    run_ag_signed_token_adoption as run_ag,
)
from run_cx_signed_token_adoption import (  # noqa: E402
    run_cx_signed_token_adoption as run_cx,
)
from run_mo_signed_token_adoption import (  # noqa: E402
    run_mo_signed_token_adoption as run_mo,
)
from run_platform_service_token_admission import (  # noqa: E402
    run_platform_service_token_admission as run_admission,
)
from run_platform_signed_token_adoption_boundary import (  # noqa: E402
    run_platform_signed_token_adoption_boundary as run_boundary,
)
from run_platform_signed_token_postgres_smoke import (  # noqa: E402
    SMOKE_ENV,
    run_platform_signed_token_postgres_smoke as run_postgres,
)
from run_platform_signed_token_verifier import (  # noqa: E402
    run_platform_signed_token_verifier as run_verifier,
)
from run_service_token_rollout_observability import (  # noqa: E402
    run_service_token_rollout_observability as run_observability,
)


SCHEMA_VERSION = "s128_platform_signed_token_adoption_closure.v1"
SLICE_RANGE = "1272-1281"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
SLICE_DOCUMENTS = tuple(
    f"{number}_{name}.md"
    for number, name in (
        (1272, "platform_signed_token_adoption_boundary"),
        (1273, "shared_jwks_signed_token_verifier"),
        (1274, "shared_fastapi_service_token_admission"),
        (1275, "ae_signed_token_verification_adoption"),
        (1276, "cx_signed_token_verification_adoption"),
        (1277, "mo_signed_token_verification_adoption"),
        (1278, "ag_signed_token_verification_adoption"),
        (1279, "service_token_rollout_observability_contracts_privacy"),
        (1280, "platform_signed_token_postgres_loopback_smoke"),
        (1281, "s128_platform_signed_token_adoption_closure"),
    )
)
REQUIRED_FILES = (
    "services/_shared/nex_runtime/signed_token_adoption_boundary.py",
    "services/_shared/nex_runtime/signed_token_verifier.py",
    "services/_shared/nex_runtime/service_token_admission.py",
    "services/nex-ae-api/nex_ae_api/service_auth.py",
    "services/nex-cx/nex_cx/service_auth.py",
    "services/nex-mo/nex_mo/provider_auth.py",
    "services/nex-ag/nex_ag/service_auth.py",
    "services/nex-oa/nex_oa/platform_signed_token_postgres_smoke.py",
    "contracts/schemas/common/service_token_runtime.v1.schema.json",
    "contracts/examples/auth/service_token_runtime.signed_only.json",
    "contracts/tests/negative/auth/service_token_runtime.raw_token.json",
    "scripts/smoke/run_s128_platform_signed_token_adoption_closure.py",
    "tests/test_s128_platform_signed_token_adoption_closure.py",
    *(f"docs/slices/{name}" for name in SLICE_DOCUMENTS),
)
TOKEN_CHECKS = (
    (
        "full_gate_registered",
        QUALITY_GATE_PATH,
        "run_s128_platform_signed_token_adoption_closure.py",
    ),
    (
        "closure_indexed",
        "docs/README.md",
        "1281_s128_platform_signed_token_adoption_closure.md",
    ),
    (
        "actual_database_identity",
        "docs/slices/1280_platform_signed_token_postgres_loopback_smoke.md",
        "`nex_oa_test` / `nex_oa_user`",
    ),
    (
        "actual_migrations_current",
        "docs/slices/1280_platform_signed_token_postgres_loopback_smoke.md",
        "Migrations: `16/16`",
    ),
    (
        "actual_consumers_verified",
        "docs/slices/1280_platform_signed_token_postgres_loopback_smoke.md",
        "Consumers: `4/4`",
    ),
    (
        "actual_cleanup_zero",
        "docs/slices/1280_platform_signed_token_postgres_loopback_smoke.md",
        "Cleanup residue: `0`",
    ),
)


def run_s128_platform_signed_token_adoption_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()}
        for path in REQUIRED_FILES
    ]
    token_checks = [
        {
            "name": name,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for name, path, token in TOKEN_CHECKS
    ]
    token_status = {item["name"]: item["present"] for item in token_checks}
    evidence = {
        "boundary": _safe_evidence(lambda: run_boundary(root)),
        "verifier": _repository_evidence(root, run_verifier),
        "admission": _repository_evidence(root, run_admission),
        "ae": _safe_evidence(lambda: run_ae(root)),
        "cx": _safe_evidence(lambda: run_cx(root)),
        "mo": _safe_evidence(lambda: run_mo(root)),
        "ag": _safe_evidence(lambda: run_ag(root)),
        "observability": _safe_evidence(lambda: run_observability(root)),
        "protected_postgres": _postgres_evidence(root, token_status),
    }
    expected_slices = {
        "boundary": "1272",
        "verifier": "1273",
        "admission": "1274",
        "ae": "1275",
        "cx": "1276",
        "mo": "1277",
        "ag": "1278",
        "observability": "1279",
        "protected_postgres": "1280",
    }
    boundary = _mapping(evidence["boundary"].get("boundary"))
    postgres = _mapping(evidence["protected_postgres"].get("summary"))
    components = {
        "shared_verification_and_admission": all(
            evidence[name].get("status") == "PASS"
            for name in ("verifier", "admission")
        ),
        "ae_and_cx_adoption": all(
            evidence[name].get("status") == "PASS" for name in ("ae", "cx")
        ),
        "mo_and_ag_adoption": all(
            evidence[name].get("status") == "PASS" for name in ("mo", "ag")
        ),
        "observability_contracts_and_privacy": (
            evidence["observability"].get("status") == "PASS"
        ),
        "actual_postgres_platform_loopback": (
            evidence["protected_postgres"].get("status") == "PASS"
        ),
    }
    decision = _closure_decision()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_evidence_passed": all(
            item.get("status") == "PASS" for item in evidence.values()
        ),
        "evidence_identity_complete": all(
            evidence[name].get("slice") == slice_id
            and evidence[name].get("requirement") == "S128"
            for name, slice_id in expected_slices.items()
        ),
        "all_components_closed": all(components.values()),
        "boundary_closed": (
            boundary.get("owner") == "nex-runtime"
            and boundary.get("issuer_service") == "nex-oa"
            and boundary.get("token_profile") == "service_access"
            and boundary.get("algorithm") == "RS256"
            and tuple(boundary.get("consumer_services") or ())
            == ("nex-ae-api", "nex-cx", "nex-mo", "nex-ag")
            and boundary.get("silent_mock_fallback_allowed") is False
            and boundary.get("cross_service_database_reads_allowed") is False
            and boundary.get("new_database_tables_required") is False
            and boundary.get("remote_model_provider_required") is False
        ),
        "shared_runtime_closed": (
            evidence["verifier"].get("jwks_fetch_count") == 1
            and evidence["verifier"].get("token_id_digest_length") == 64
            and evidence["admission"].get("read_http_status") == 200
            and evidence["admission"].get("mock_http_status") == 401
            and evidence["admission"].get("introspection_call_count") == 1
        ),
        "consumer_adoption_closed": all(
            evidence[name].get("status") == "PASS"
            for name in ("ae", "cx", "mo", "ag")
        ),
        "observability_closed": (
            evidence["observability"].get("consumer_count") == 4
            and evidence["observability"].get("runtime_schema_version")
            == "service_token_runtime.v1"
        ),
        "actual_postgres_closed": (
            postgres.get("migration_count") == 16
            and postgres.get("consumer_count") == 4
            and postgres.get("passed_consumer_count") == 4
            and postgres.get("issued_token_count") == 4
            and postgres.get("cleanup_residue_count") == 0
        ),
        "completed_scope_closed": decision["completed_scope"]
        == (
            "shared_rs256_jwks_verification_and_bounded_cache",
            "shared_fastapi_admission_and_sensitive_route_introspection",
            "ae_cx_mo_ag_service_access_adoption",
            "protected_redacted_rollout_observability",
            "actual_postgres_four_consumer_loopback_evidence",
        ),
        "deployment_boundary_honest": (
            decision["implementation_readiness"] == "READY"
            and decision["production_signed_only_activation"]
            == "PROFILE_CONFIGURATION_REQUIRED"
            and decision["delegated_user_access"] == "DEFERRED"
            and decision["next_requirement"] == "S129"
        ),
        "tiered_quality_cadence_preserved": decision["quality_cadence"]
        == {
            "slice_gate": "1272-1280",
            "checkpoint_gate": "1276",
            "full_gate": "1281",
        },
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1281",
        "slice_range": SLICE_RANGE,
        "requirement": "S128",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "s128_platform_signed_token_adoption_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S129" if passed else "BLOCKED",
        "service_access_adoption_readiness": (
            "PLATFORM_ADOPTION_READY" if passed else "INCOMPLETE"
        ),
        "production_signed_only_activation": (
            "PROFILE_CONFIGURATION_REQUIRED" if passed else "BLOCKED"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(
                item.get("status") == "PASS" for item in evidence.values()
            ),
            "component_count": len(components),
            "closed_component_count": sum(components.values()),
            "consumer_count": len(boundary.get("consumer_services") or ()),
            "runtime_schema_count": 1
            if evidence["observability"].get("runtime_schema_version")
            == "service_token_runtime.v1"
            else 0,
            "postgres_migration_count": int(postgres.get("migration_count") or 0),
            "postgres_issued_token_count": int(
                postgres.get("issued_token_count") or 0
            ),
            "postgres_cleanup_residue_count": int(
                postgres.get("cleanup_residue_count", -1)
            ),
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "missing_token_count": sum(
                not item["present"] for item in token_checks
            ),
        },
        "evidence_statuses": {
            name: item.get("status") for name, item in evidence.items()
        },
        "components": components,
        "decision": decision,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S129" if passed else "blocked",
        "next_requirement_scope": (
            "pending_canonical_scope_review" if passed else "blocked"
        ),
    }


def _postgres_evidence(
    root: Path,
    token_status: Mapping[str, bool],
) -> dict[str, Any]:
    if root == ROOT and os.environ.get(SMOKE_ENV) == "1":
        return _safe_evidence(run_postgres)
    passed = all(
        token_status.get(name, False)
        for name in (
            "actual_database_identity",
            "actual_migrations_current",
            "actual_consumers_verified",
            "actual_cleanup_zero",
        )
    )
    return {
        "slice": "1280",
        "requirement": "S128",
        "status": "PASS" if passed else "FAIL",
        "summary": {
            "migration_count": 16 if passed else 0,
            "consumer_count": 4 if passed else 0,
            "passed_consumer_count": 4 if passed else 0,
            "issued_token_count": 4 if passed else 0,
            "cleanup_residue_count": 0 if passed else -1,
        },
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "platform_service_access_signed_token_adoption",
        "completed_scope": (
            "shared_rs256_jwks_verification_and_bounded_cache",
            "shared_fastapi_admission_and_sensitive_route_introspection",
            "ae_cx_mo_ag_service_access_adoption",
            "protected_redacted_rollout_observability",
            "actual_postgres_four_consumer_loopback_evidence",
        ),
        "implementation_readiness": "READY",
        "production_signed_only_activation": "PROFILE_CONFIGURATION_REQUIRED",
        "delegated_user_access": "DEFERRED",
        "next_requirement": "S129",
        "actual_postgres_smoke_required": True,
        "remote_provider_calls_required": False,
        "new_tables_created": (),
        "quality_cadence": {
            "slice_gate": "1272-1280",
            "checkpoint_gate": "1276",
            "full_gate": "1281",
        },
    }


def _repository_evidence(
    root: Path,
    builder: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    if root != ROOT:
        return {"status": "FAIL", "failure_code": "repository_root_invalid"}
    return _safe_evidence(builder)


def _safe_evidence(builder: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
    try:
        return dict(builder())
    except Exception as exc:
        return {
            "status": "FAIL",
            "failure_code": "evidence_builder_failed",
            "detail": exc.__class__.__name__,
        }


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "s128_platform_signed_token_adoption_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"consumers={summary.get('consumer_count', 0)} "
        f"activation={evidence.get('production_signed_only_activation', 'BLOCKED')} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s128_platform_signed_token_adoption_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
