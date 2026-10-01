#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-mo"):
    sys.path.insert(0, str(path))

from nex_mo.catalog_lifecycle_repository import (  # noqa: E402
    InMemoryCatalogLifecycleRepository,
)
from nex_mo.catalog_lifecycle_service import CatalogLifecycleService  # noqa: E402
from nex_mo.operations_api import register_operations_routes  # noqa: E402
from nex_mo.operations_service import MOOperationsService  # noqa: E402
from nex_mo.provider_readiness_service import ProviderReadinessService  # noqa: E402
from nex_mo.provider_telemetry import InMemoryProviderTelemetryStore  # noqa: E402
from nex_mo.remote_provider import (  # noqa: E402
    build_remote_embedding_execution_config,
    build_remote_generation_execution_config,
    build_remote_reranker_execution_config,
)
from nex_mo.runtime_observability_service import RuntimeObservabilityService  # noqa: E402
from nex_runtime import issue_mock_service_token  # noqa: E402


NOW = datetime(2026, 10, 1, tzinfo=UTC)
SCHEMA = "contracts/schemas/service/nex_mo/operations_snapshot.v1.schema.json"
FORBIDDEN_TOKENS = (
    "api_key",
    "authorization",
    "database_url",
    "password",
    "provider_endpoint",
    "ssh_target",
)


def build_deterministic_operations_app() -> FastAPI:
    environment: dict[str, str] = {}
    catalog = CatalogLifecycleService(
        InMemoryCatalogLifecycleRepository(),
        clock=lambda: "2026-10-01T00:00:00Z",
    )
    catalog.ensure_bootstrap()
    readiness = ProviderReadinessService(environ=environment, now=lambda: NOW)
    runtime = RuntimeObservabilityService(environ=environment, now=lambda: NOW)
    telemetry = InMemoryProviderTelemetryStore()
    configs = (
        build_remote_embedding_execution_config(environment),
        build_remote_reranker_execution_config(environment),
        build_remote_generation_execution_config(environment),
    )
    operations = MOOperationsService(
        catalog_service=catalog,
        readiness_service=readiness,
        runtime_service=runtime,
        telemetry_reader=lambda: telemetry.snapshot(configs),
        environ=environment,
        now=lambda: NOW,
    )
    app = FastAPI()
    app.state.mo_operations_service = operations
    register_operations_routes(app, service=operations)
    return app


def run_mo_operations_integrated_acceptance(
    root: Path = ROOT,
    *,
    app: FastAPI | None = None,
) -> dict[str, Any]:
    client = TestClient(app or build_deterministic_operations_app())
    token = issue_mock_service_token(service_id="nex-ag", audience="nex-mo")
    headers = {"Authorization": f"Bearer {token.access_token}"}
    unauthorized = client.get("/api/v1/operations-snapshot")
    baseline = client.get("/api/v1/operations-snapshot", headers=headers)
    refreshed = client.get(
        "/api/v1/operations-snapshot?force_refresh=true",
        headers=headers,
    )
    payload = refreshed.json() if refreshed.status_code == 200 else {}
    schema = _read_json(root / SCHEMA)
    schema_errors = (
        list(Draft202012Validator(schema).iter_errors(payload)) if schema else [None]
    )
    sources = {
        item.get("source"): item
        for item in payload.get("sources", [])
        if isinstance(item, Mapping)
    }
    capabilities = {
        item.get("provider_capability"): item
        for item in payload.get("capabilities", [])
        if isinstance(item, Mapping)
    }
    serialized = json.dumps(payload, sort_keys=True).lower()
    checks = {
        "authentication_required": unauthorized.status_code == 401,
        "baseline_snapshot_ready": baseline.status_code == 200
        and baseline.json().get("operations_status") == "READY",
        "force_refresh_snapshot_ready": refreshed.status_code == 200
        and payload.get("operations_status") == "READY",
        "all_sources_ready_and_fresh": set(sources)
        == {"catalog", "readiness", "telemetry", "runtime"}
        and all(
            item.get("status") == "READY" and item.get("fresh") is True
            for item in sources.values()
        ),
        "all_capabilities_ready": set(capabilities)
        == {"embedding", "reranking", "generation"}
        and all(
            item.get("operations_status") == "READY"
            for item in capabilities.values()
        ),
        "canonical_schema_valid": not schema_errors,
        "private_values_omitted": not any(token in serialized for token in FORBIDDEN_TOKENS),
        "acceptance_is_non_live": payload.get("provider_mode") == "mock"
        and payload.get("acceptance_status") == "NOT_RUN",
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_operations_integrated_acceptance.v1",
        "slice": "1188",
        "requirement": "S119",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_operations_integration_failed",
        "checks": checks,
        "summary": {
            "source_count": len(sources),
            "ready_source_count": sum(
                item.get("status") == "READY" for item in sources.values()
            ),
            "capability_count": len(capabilities),
            "ready_capability_count": sum(
                item.get("operations_status") == "READY"
                for item in capabilities.values()
            ),
            "schema_error_count": len(schema_errors),
            "unauthorized_status": unauthorized.status_code,
            "baseline_status": baseline.status_code,
            "refresh_status": refreshed.status_code,
        },
        "next_slice": "1189" if passed else "blocked",
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_operations_integrated_acceptance="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"sources={summary.get('ready_source_count', 0)}/"
        f"{summary.get('source_count', 0)} "
        f"capabilities={summary.get('ready_capability_count', 0)}/"
        f"{summary.get('capability_count', 0)} "
        f"schema_errors={summary.get('schema_error_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_operations_integrated_acceptance()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
