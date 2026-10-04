#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_route_client_topology_inventory.v1"
SERVICE_PACKAGE_BY_DIRECTORY = {
    "nex-oa": "oa",
    "nex-ae-api": "ae_api",
    "nex-cx": "cx",
    "nex-mo": "mo",
    "nex-ag": "ag",
}
INTER_SERVICE_IMPORT = re.compile(
    r"^(?:from|import)\s+nex_(oa|ae_api|cx|mo|ag)(?:\.|\s|$)",
    re.MULTILINE,
)


@dataclass(frozen=True)
class EdgeEvidence:
    edge: str
    capability: str
    relative_path: str
    token: str


HTTP_EDGES = (
    EdgeEvidence(
        "ae-web->ae-api",
        "browser_facade",
        "apps/nex-ae-web/src/clientRegistry.js",
        "createAeWebClients",
    ),
    EdgeEvidence(
        "ae-api->oa",
        "user_session",
        "services/nex-ae-api/nex_ae_api/oa_session_client.py",
        "class HttpOaUserSessionClient",
    ),
    EdgeEvidence(
        "ae-api->cx",
        "upload",
        "services/nex-ae-api/nex_ae_api/uploads.py",
        "class HttpCxUploadClient",
    ),
    EdgeEvidence(
        "ae-api->cx",
        "retrieval",
        "services/nex-ae-api/nex_ae_api/retrieval.py",
        "class HttpCxRetrievalClient",
    ),
    EdgeEvidence(
        "ae-api->cx",
        "generation",
        "services/nex-ae-api/nex_ae_api/chat.py",
        "class HttpCxGenerationClient",
    ),
    EdgeEvidence(
        "cx->mo",
        "embedding",
        "services/nex-cx/nex_cx/embedding_index.py",
        "class HttpMoEmbeddingClient",
    ),
    EdgeEvidence(
        "cx->mo",
        "reranking",
        "services/nex-cx/nex_cx/retrieval.py",
        "class HttpMoRerankClient",
    ),
    EdgeEvidence(
        "cx->mo",
        "generation",
        "services/nex-cx/nex_cx/generation.py",
        "class HttpMoGenerationClient",
    ),
    EdgeEvidence(
        "ag->ae-api/cx",
        "generation_audit",
        "services/nex-ag/nex_ag/generation_audit.py",
        "class HttpGenerationAuditSourceClient",
    ),
    EdgeEvidence(
        "ag->ae-api",
        "artifact_operations",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "class HttpAeArtifactOperationsClient",
    ),
    EdgeEvidence(
        "ag->all-services",
        "readiness",
        "services/nex-ag/nex_ag/readiness.py",
        "class HttpServiceStatusClient",
    ),
)

AG_CROSS_SERVICE_DATABASE_EVIDENCE = (
    (
        "operations",
        "services/nex-ag/nex_ag/operations.py",
        "ag_operations_source_database_env(",
    ),
    (
        "processing",
        "services/nex-ag/nex_ag/processing_operations.py",
        "ag_operations_source_database_env(",
    ),
    (
        "retrieval",
        "services/nex-ag/nex_ag/retrieval_operations.py",
        "ag_operations_source_database_env(",
    ),
    (
        "remediation",
        "services/nex-ag/nex_ag/remediation_execution_operations.py",
        "ag_operations_source_database_env(",
    ),
)


def run_platform_route_client_topology_inventory(
    root: Path = ROOT,
) -> dict[str, Any]:
    edges = [
        {
            "edge": item.edge,
            "capability": item.capability,
            "path": item.relative_path,
            "transport": "http",
            "present": item.token in _read_text(root / item.relative_path),
        }
        for item in HTTP_EDGES
    ]
    database_couplings = [
        {
            "projection": projection,
            "path": path,
            "present": token in _read_text(root / path),
            "classification": "cross_service_database_read_candidate",
        }
        for projection, path, token in AG_CROSS_SERVICE_DATABASE_EVIDENCE
    ]
    cross_service_imports = _cross_service_package_imports(root)
    base_url_occurrences = _base_url_configuration_occurrences(root)
    checks = {
        "all_expected_http_edges_present": all(item["present"] for item in edges),
        "no_cross_service_python_package_imports": not cross_service_imports,
        "ag_database_coupling_inventory_complete": all(
            item["present"] for item in database_couplings
        ),
        "base_url_configuration_is_discoverable": bool(base_url_occurrences),
    }
    issues = [
        {
            "category": "http_edge_evidence_missing",
            "edge": item["edge"],
            "path": item["path"],
        }
        for item in edges
        if not item["present"]
    ]
    issues.extend(
        {
            "category": "cross_service_package_import",
            **item,
        }
        for item in cross_service_imports
    )
    passed = all(checks.values())
    present_db_couplings = [item for item in database_couplings if item["present"]]
    return {
        "inventory_schema_version": SCHEMA_VERSION,
        "slice": "1303",
        "requirement": "S131",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "platform_route_client_topology_inventory_failed"
        ),
        "http_edges": edges,
        "cross_service_package_imports": cross_service_imports,
        "ag_cross_service_database_couplings": present_db_couplings,
        "base_url_configuration_occurrences": base_url_occurrences,
        "checks": checks,
        "issues": issues,
        "findings": {
            "http_edge_count": len(edges),
            "logical_edge_count": len({item["edge"] for item in edges}),
            "cross_service_package_import_count": len(cross_service_imports),
            "ag_cross_service_database_coupling_count": len(present_db_couplings),
            "base_url_configuration_count": len(base_url_occurrences),
            "canonical_topology_manifest_present": False,
        },
        "refactoring_candidates": [
            {
                "priority": "P0",
                "owner": "nex-ag",
                "gap": "replace cross-service PostgreSQL projections with service API clients",
                "target_requirement": "S132",
            },
            {
                "priority": "P1",
                "owner": "platform_integration",
                "gap": "centralize typed service endpoint configuration without sharing domain logic",
                "target_requirement": "S132",
            },
            {
                "priority": "P1",
                "owner": "platform_integration",
                "gap": "publish an explicit runtime topology manifest and readiness dependency graph",
                "target_requirement": "S132",
            },
        ],
        "decision": {
            "service_api_edges_are_reusable": True,
            "cross_service_package_imports_allowed": False,
            "cross_service_database_reads_allowed": False,
            "database_couplings_are_accepted_target_state": False,
            "mutation_performed": False,
            "next_slice": "1304",
        },
    }


def _cross_service_package_imports(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for directory, owner_package in SERVICE_PACKAGE_BY_DIRECTORY.items():
        service_root = root / "services" / directory
        if not service_root.is_dir():
            continue
        for path in service_root.rglob("*.py"):
            for target in INTER_SERVICE_IMPORT.findall(_read_text(path)):
                if target != owner_package:
                    findings.append(
                        {
                            "owner": directory,
                            "target_package": f"nex_{target}",
                            "path": str(path.relative_to(root)),
                        }
                    )
    return sorted(findings, key=lambda item: (item["owner"], item["path"]))


def _base_url_configuration_occurrences(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for directory in ("nex-ae-api", "nex-cx", "nex-ag"):
        service_root = root / "services" / directory
        if not service_root.is_dir():
            continue
        for path in service_root.rglob("*.py"):
            text = _read_text(path)
            for env_name in sorted(set(re.findall(r'"(NEX_[A-Z_]+_BASE_URL)"', text))):
                findings.append(
                    {
                        "service": directory,
                        "environment": env_name,
                        "path": str(path.relative_to(root)),
                    }
                )
    return findings


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return (
            "platform_route_client_topology=fail "
            f"issues={len(evidence.get('issues') or [])}"
        )
    findings = evidence.get("findings") or {}
    return (
        "platform_route_client_topology=pass "
        f"http={findings.get('http_edge_count', 0)} "
        f"logical={findings.get('logical_edge_count', 0)} "
        f"cross_imports={findings.get('cross_service_package_import_count', 0)} "
        f"ag_db_couplings={findings.get('ag_cross_service_database_coupling_count', 0)} "
        f"topology_manifest={findings.get('canonical_topology_manifest_present')} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_route_client_topology_inventory()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
