#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_ae_artifact_ag_audit_path_audit.v1"


def run_platform_ae_artifact_ag_audit_path_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    ae_artifacts = _read_text(root / "services/nex-ae-api/nex_ae_api/artifacts.py")
    ae_lineage = _read_text(
        root / "services/nex-ae-api/nex_ae_api/generated_response_lineage.py"
    )
    ae_handoff = _read_text(
        root / "services/nex-ae-api/nex_ae_api/generated_response_handoff.py"
    )
    ag_generation = _read_text(root / "services/nex-ag/nex_ag/generation_audit.py")
    ag_artifacts = _read_text(root / "services/nex-ag/nex_ag/artifact_operations.py")
    cx_generation = _read_text(root / "services/nex-cx/nex_cx/generation.py")

    ag_generation_operations = (
        "get_cx_generation",
        "get_cx_generation_events",
        "get_ae_artifact_handoff",
        "get_ae_recovery_request",
    )
    lineage_fields = (
        "interaction_id",
        "cx_generation_id",
        "content_sha256",
    )
    cx_owner_headers = ("CX_TENANT_HEADER", "CX_SUBJECT_HEADER")
    generation_client_has_owner_headers = any(
        token in ag_generation
        for token in ("X-NEX-Tenant-ID", "X-NEX-Subject-ID", "cx_owner_headers")
    )
    cx_generation_requires_owner_headers = all(
        token in cx_generation for token in cx_owner_headers
    )
    checks = {
        "ae_generated_response_lineage_is_explicit": all(
            token in ae_lineage for token in lineage_fields
        ),
        "ae_artifact_handoff_attaches_generation_lineage": (
            "attach_generated_response_lineage" in ae_handoff
            and "/api/v1/artifact-handoffs/{artifact_handoff_id}" in ae_artifacts
        ),
        "ag_generation_audit_http_client_is_complete": (
            "class HttpGenerationAuditSourceClient" in ag_generation
            and all(token in ag_generation for token in ag_generation_operations)
        ),
        "ag_artifact_operations_http_client_is_present": (
            "class HttpAeArtifactOperationsClient" in ag_artifacts
            and 'audience=AE_ARTIFACT_SOURCE_SERVICE_ID' in ag_artifacts
        ),
        "ag_clients_propagate_service_identity_and_trace": all(
            token in source
            for source in (ag_generation, ag_artifacts)
            for token in ('"X-Request-ID"', '"traceparent"', '"X-Service-ID": "nex-ag"')
        ),
        "ag_generation_projection_has_raw_field_denylist": (
            "FORBIDDEN_DETAIL_KEYS" in ag_generation
            and '"raw_prompt"' in ag_generation
            and '"raw_output"' in ag_generation
            and '"storage_path"' in ag_generation
        ),
        "cx_generation_reads_are_owner_scoped": cx_generation_requires_owner_headers,
    }
    issues = [name for name, passed in checks.items() if not passed]
    owner_context_compatible = (
        not cx_generation_requires_owner_headers or generation_client_has_owner_headers
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1308",
        "requirement": "S131",
        "status": "PASS" if not issues else "FAIL",
        "failure_code": None if not issues else "platform_ae_artifact_ag_audit_path_failed",
        "checks": checks,
        "issues": issues,
        "findings": {
            "ae_lineage_field_count": len(lineage_fields),
            "ag_generation_source_operation_count": len(ag_generation_operations),
            "ag_artifact_http_client_present": "class HttpAeArtifactOperationsClient"
            in ag_artifacts,
            "cx_generation_reads_require_owner_context": cx_generation_requires_owner_headers,
            "ag_generation_client_sends_owner_context": generation_client_has_owner_headers,
            "ag_generation_client_is_cx_owner_compatible": owner_context_compatible,
            "dedicated_cx_admin_audit_projection_present": False,
            "ag_cross_service_database_fallback_count": 4,
        },
        "refactoring_candidates": [
            {
                "priority": "P0",
                "owner": "nex-cx/nex-ag",
                "gap": "add an ADMIN-scoped redacted CX generation audit projection API and make AG use it",
                "target_requirement": "S138",
            },
            {
                "priority": "P0",
                "owner": "nex-ag",
                "gap": "remove cross-service database projection fallbacks after equivalent service APIs exist",
                "target_requirement": "S132/S138",
            },
            {
                "priority": "P1",
                "owner": "nex-ag",
                "gap": "unify AE endpoint and service-token configuration across generation audit and artifact operations clients",
                "target_requirement": "S132",
            },
        ],
        "decision": {
            "ae_owns_artifact_and_response_lineage": True,
            "ag_owns_redacted_operator_projection_only": True,
            "ag_may_bypass_owner_scope_by_reading_service_database": False,
            "ag_should_assert_unknown_user_owner_context": False,
            "dedicated_admin_projection_is_recommended": True,
            "mutation_performed": False,
            "next_slice": "1309",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"platform_ae_artifact_ag_audit_path=fail issues={len(evidence.get('issues') or [])}"
    findings = evidence.get("findings") or {}
    return (
        "platform_ae_artifact_ag_audit_path=pass "
        f"ag_ops={findings.get('ag_generation_source_operation_count', 0)} "
        f"owner_required={findings.get('cx_generation_reads_require_owner_context')} "
        f"owner_sent={findings.get('ag_generation_client_sends_owner_context')} "
        f"owner_compatible={findings.get('ag_generation_client_is_cx_owner_compatible')} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_ae_artifact_ag_audit_path_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
