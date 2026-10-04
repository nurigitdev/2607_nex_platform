#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_ae_cx_integration_path_audit.v1"


@dataclass(frozen=True)
class ClientEvidence:
    capability: str
    relative_path: str
    class_name: str


CLIENTS = (
    ClientEvidence("upload", "services/nex-ae-api/nex_ae_api/uploads.py", "HttpCxUploadClient"),
    ClientEvidence("documents", "services/nex-ae-api/nex_ae_api/documents.py", "HttpCxDocumentLibraryClient"),
    ClientEvidence("retrieval", "services/nex-ae-api/nex_ae_api/retrieval.py", "HttpCxRetrievalClient"),
    ClientEvidence("generation", "services/nex-ae-api/nex_ae_api/chat.py", "HttpCxGenerationClient"),
    ClientEvidence("async_generation", "services/nex-ae-api/nex_ae_api/cx_async_generation_client.py", "HttpCxAsyncGenerationClient"),
    ClientEvidence("recovery", "services/nex-ae-api/nex_ae_api/recovery_requests.py", "HttpCxRecoverySourceClient"),
    ClientEvidence("repair", "services/nex-ae-api/nex_ae_api/repaired_response_client.py", "HttpCxRepairedResponseSourceClient"),
    ClientEvidence("artifact_source", "services/nex-ae-api/nex_ae_api/artifacts.py", "HttpCxArtifactSourceClient"),
)

CX_ROUTE_EVIDENCE = (
    ("upload", "services/nex-cx/nex_cx/ingestion.py", '"/api/v1/documents/uploads"'),
    ("document", "services/nex-cx/nex_cx/ingestion.py", '"/api/v1/documents/{document_id}"'),
    ("retrieval", "services/nex-cx/nex_cx/retrieval.py", '"/api/v1/retrieval/context"'),
    ("generation", "services/nex-cx/nex_cx/generation.py", '"/api/v1/generations"'),
    ("async_generation", "services/nex-cx/nex_cx/async_generation_operations.py", '"/api/v1/generation-jobs"'),
)


def run_platform_ae_cx_integration_path_audit(root: Path = ROOT) -> dict[str, Any]:
    clients = []
    for item in CLIENTS:
        source = _read_text(root / item.relative_path)
        clients.append(
            {
                "capability": item.capability,
                "path": item.relative_path,
                "class_name": item.class_name,
                "present": f"class {item.class_name}" in source,
                "service_token": 'audience="nex-cx"' in source,
                "owner_headers": "cx_owner_headers" in source,
                "request_id": '"X-Request-ID"' in source,
                "traceparent": '"traceparent"' in source,
            }
        )
    routes = [
        {
            "capability": capability,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for capability, path, token in CX_ROUTE_EVIDENCE
    ]
    owner_context = _read_text(
        root / "services/nex-ae-api/nex_ae_api/cx_owner_context.py"
    )
    upload_source = _read_text(root / "services/nex-ae-api/nex_ae_api/uploads.py")
    async_source = _read_text(
        root / "services/nex-ae-api/nex_ae_api/cx_async_generation_client.py"
    )
    ae_package = root / "services/nex-ae-api/nex_ae_api"
    cross_database_references = _matching_python_files(
        ae_package,
        "NEX_CX_DATABASE_URL",
        root=root,
    )
    client_contract_complete = all(
        item[key]
        for item in clients
        for key in ("present", "service_token", "owner_headers", "request_id", "traceparent")
    )
    checks = {
        "all_ae_cx_clients_present": all(item["present"] for item in clients),
        "all_ae_cx_clients_propagate_trust_owner_and_trace": client_contract_complete,
        "cx_core_routes_present": all(item["present"] for item in routes),
        "upload_owner_is_overridden_from_browser_context": (
            "_browser_owner_scoped_payload(" in upload_source
            and "auth_context.browser_context" in upload_source
        ),
        "async_generation_uses_idempotency_key": 'headers["Idempotency-Key"]'
        in async_source,
        "ae_does_not_read_cx_database": not cross_database_references,
    }
    issues = [name for name, passed in checks.items() if not passed]
    has_local_owner_defaults = all(
        token in owner_context
        for token in (
            'DEFAULT_TENANT_ID = "local-tenant"',
            'DEFAULT_SUBJECT_ID = "local-user"',
        )
    )
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1306",
        "requirement": "S131",
        "status": "PASS" if not issues else "FAIL",
        "failure_code": None if not issues else "platform_ae_cx_integration_path_audit_failed",
        "checks": checks,
        "issues": issues,
        "clients": clients,
        "cx_routes": routes,
        "cross_database_references": cross_database_references,
        "findings": {
            "ae_cx_client_count": len(clients),
            "cx_core_route_count": len(routes),
            "duplicated_base_url_owner_count": sum(
                "NEX_CX_BASE_URL" in _read_text(root / item.relative_path)
                for item in CLIENTS
            ),
            "local_owner_fallback_present": has_local_owner_defaults,
            "cross_database_reference_count": len(cross_database_references),
            "integrated_postgres_journey_proven_in_this_slice": False,
        },
        "refactoring_candidates": [
            {
                "priority": "P0",
                "owner": "nex-ae-api",
                "gap": "fail closed on missing owner scope in protected profiles instead of using local owner defaults",
                "target_requirement": "S134/S135",
            },
            {
                "priority": "P1",
                "owner": "nex-ae-api",
                "gap": "centralize common CX HTTP transport, service auth, owner, trace, timeout, and error translation",
                "target_requirement": "S132",
            },
            {
                "priority": "P1",
                "owner": "platform_integration",
                "gap": "prove upload through async generation as one restart-safe PostgreSQL journey",
                "target_requirement": "S135/S137",
            },
        ],
        "decision": {
            "ae_cx_http_boundary_is_reusable": True,
            "ae_cx_database_sharing_allowed": False,
            "owner_fallback_is_accepted_protected_state": False,
            "mutation_performed": False,
            "next_slice": "1307",
        },
    }


def _matching_python_files(path: Path, token: str, *, root: Path) -> list[str]:
    if not path.is_dir():
        return []
    return sorted(
        str(candidate.relative_to(root))
        for candidate in path.rglob("*.py")
        if token in _read_text(candidate)
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"platform_ae_cx_integration_path=fail issues={len(evidence.get('issues') or [])}"
    findings = evidence.get("findings") or {}
    return (
        "platform_ae_cx_integration_path=pass "
        f"clients={findings.get('ae_cx_client_count', 0)} "
        f"routes={findings.get('cx_core_route_count', 0)} "
        f"owner_fallback={findings.get('local_owner_fallback_present')} "
        f"cross_db={findings.get('cross_database_reference_count', 0)} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_ae_cx_integration_path_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
