#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterator, Mapping

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))


PROTECTED_REQUESTS = (
    ("GET", "/internal/v1/auth/service-claim"),
    ("GET", "/internal/v1/jobs/missing"),
    ("POST", "/internal/v1/jobs/missing/cancel"),
    ("POST", "/internal/v1/jobs/missing/retry"),
    ("POST", "/internal/v1/jobs/missing/replay"),
    ("POST", "/internal/v1/service-logs/retention/purge"),
    ("GET", "/internal/v1/service-logs/retention/history"),
    ("GET", "/internal/v1/service-logs/retention/history/missing"),
    ("GET", "/api/v1/provider-routes"),
    ("GET", "/api/v1/provider-profiles"),
    ("GET", "/api/v1/provider-route-health"),
    ("GET", "/api/v1/provider-telemetry"),
    ("GET", "/api/v1/model-runtime-observability"),
    ("POST", "/api/v1/embeddings"),
    ("POST", "/api/v1/rerank"),
    ("POST", "/api/v1/generations"),
)
PROVIDER_REQUESTS = (
    ("provider_routes", "GET", "/api/v1/provider-routes", None, "provider_route_list"),
    (
        "provider_profiles",
        "GET",
        "/api/v1/provider-profiles",
        None,
        "model_profile_list",
    ),
    (
        "provider_readiness",
        "GET",
        "/api/v1/provider-route-health",
        None,
        "provider_readiness",
    ),
    (
        "provider_telemetry",
        "GET",
        "/api/v1/provider-telemetry",
        None,
        "provider_telemetry_snapshot",
    ),
    (
        "runtime_observability",
        "GET",
        "/api/v1/model-runtime-observability",
        None,
        "runtime_observability",
    ),
    (
        "embedding",
        "POST",
        "/api/v1/embeddings",
        {"inputs": ["contract parity evidence"]},
        "embedding_response",
    ),
    (
        "reranking",
        "POST",
        "/api/v1/rerank",
        {"query": "contract parity", "documents": ["evidence one", "evidence two"]},
        "rerank_response",
    ),
    (
        "generation",
        "POST",
        "/api/v1/generations",
        {"prompt": "Summarize the contract parity evidence."},
        "generation_response",
    ),
)
ERROR_REQUESTS = (
    (
        "provider_bad_request",
        "POST",
        "/api/v1/embeddings",
        {"inputs": []},
        400,
    ),
    (
        "provider_not_found",
        "POST",
        "/api/v1/embeddings",
        {"alias": "missing-provider", "inputs": ["evidence"]},
        404,
    ),
    (
        "provider_forbidden_field",
        "POST",
        "/api/v1/generations",
        {
            "prompt": "Summarize evidence.",
            "provider_url": "https://forbidden.invalid",
        },
        422,
    ),
    (
        "job_not_found",
        "GET",
        "/internal/v1/jobs/missing",
        None,
        404,
    ),
    (
        "retention_invalid",
        "POST",
        "/internal/v1/service-logs/retention/purge",
        {},
        422,
    ),
    (
        "retention_history_not_found",
        "GET",
        "/internal/v1/service-logs/retention/history/missing",
        None,
        404,
    ),
)


def run_mo_contract_http_smoke(
    root: Path = ROOT,
    *,
    observations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    observed = dict(observations) if observations is not None else _exercise_http(root)
    auth_statuses = _int_list(observed.get("unauthorized_statuses"))
    provider_results = _mapping_list(observed.get("provider_results"))
    error_results = _mapping_list(observed.get("error_results"))
    checks = {
        "local_mock_profile_enforced": observed.get("profile") == "local_mock",
        "memory_persistence_enforced": observed.get("persistence_mode") == "memory",
        "external_http_blocked": observed.get("external_request_count") == 0,
        "root_response_schema_valid": observed.get("root_status") == 200
        and observed.get("root_schema_valid") is True,
        "service_claim_authenticated": observed.get("service_claim_status") == 200,
        "all_protected_routes_reject_missing_auth": len(auth_statuses) == 16
        and all(status == 401 for status in auth_statuses),
        "all_provider_success_shapes_valid": len(provider_results) == 8
        and all(
            item.get("status") == 200 and item.get("schema_valid") is True
            for item in provider_results
        ),
        "documented_error_statuses_observed": len(error_results) == 6
        and all(item.get("status") == item.get("expected_status") for item in error_results),
        "evidence_is_payload_free": observed.get("payload_content_recorded") is False,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_contract_http_smoke.v1",
        "slice": "1139",
        "requirement": "S114",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_contract_http_smoke_failed",
        "checks": checks,
        "summary": {
            "protected_operation_count": len(auth_statuses),
            "unauthorized_rejection_count": sum(status == 401 for status in auth_statuses),
            "provider_success_count": sum(
                item.get("status") == 200 and item.get("schema_valid") is True
                for item in provider_results
            ),
            "provider_contract_count": len(provider_results),
            "error_case_count": len(error_results),
            "matched_error_count": sum(
                item.get("status") == item.get("expected_status")
                for item in error_results
            ),
            "external_request_count": _nonnegative_int(
                observed.get("external_request_count")
            ),
        },
        "provider_results": provider_results,
        "error_results": error_results,
        "next_slice": "1140" if passed else "blocked",
    }


def _exercise_http(root: Path) -> dict[str, Any]:
    with _temporary_environment(
        {"NEX_PROFILE": "local_mock", "NEX_MO_PROVIDER_MODE": "mock"}
    ):
        with _blocked_external_http() as external_calls:
            app, runtime = _build_isolated_app()
            client = TestClient(app)
            headers = _auth_headers()
            root_response = client.get("/")
            root_schema = _root_schema(root)
            unauthorized_statuses = [
                client.request(
                    method,
                    path,
                    json={} if method == "POST" else None,
                ).status_code
                for method, path in PROTECTED_REQUESTS
            ]
            provider_results = []
            for name, method, path, payload, schema_name in PROVIDER_REQUESTS:
                response = client.request(method, path, json=payload, headers=headers)
                provider_results.append(
                    {
                        "name": name,
                        "status": response.status_code,
                        "schema_valid": _schema_valid(root, schema_name, response.json()),
                    }
                )
            error_results = []
            for name, method, path, payload, expected_status in ERROR_REQUESTS:
                response = client.request(method, path, json=payload, headers=headers)
                error_results.append(
                    {
                        "name": name,
                        "status": response.status_code,
                        "expected_status": expected_status,
                    }
                )
            return {
                "profile": root_response.json().get("profile"),
                "persistence_mode": runtime.mode,
                "external_request_count": len(external_calls),
                "root_status": root_response.status_code,
                "root_schema_valid": _validator_accepts(
                    root_schema, root_response.json()
                ),
                "service_claim_status": client.get(
                    "/internal/v1/auth/service-claim", headers=headers
                ).status_code,
                "unauthorized_statuses": unauthorized_statuses,
                "provider_results": provider_results,
                "error_results": error_results,
                "payload_content_recorded": False,
            }


def _build_isolated_app() -> tuple[Any, Any]:
    from nex_mo.provider_readiness_api import register_provider_readiness_routes
    from nex_mo.provider_readiness_service import ProviderReadinessService
    from nex_mo.providers import register_mock_provider_routes
    from nex_mo.runtime_observability_api import register_runtime_observability_routes
    from nex_mo.runtime_observability_service import RuntimeObservabilityService
    from nex_runtime import (
        SERVICE_SPECS,
        build_service_app,
        build_service_persistence_runtime,
        register_service_job_control_routes,
        register_service_log_retention_routes,
    )

    spec = SERVICE_SPECS["nex-mo"]
    app = build_service_app(spec)
    runtime = build_service_persistence_runtime(
        service_id=spec.service_id,
        database_env=spec.database_env,
        environ={},
        mode="memory",
    )
    app.state.nex_persistence = runtime
    register_service_job_control_routes(
        app,
        service_id=spec.service_id,
        job_queue=runtime.job_queue,
    )
    register_service_log_retention_routes(
        app,
        service_id=spec.service_id,
        store=runtime.service_log_store,
    )
    register_mock_provider_routes(app)
    register_provider_readiness_routes(
        app,
        service=ProviderReadinessService(environ={"NEX_MO_PROVIDER_MODE": "mock"}),
    )
    register_runtime_observability_routes(
        app,
        service=RuntimeObservabilityService(environ={}),
    )
    return app, runtime


@contextmanager
def _blocked_external_http() -> Iterator[list[str]]:
    import nex_mo.remote_provider as remote_provider

    calls: list[str] = []
    original = remote_provider.httpx.request

    def reject_external_request(*args: Any, **kwargs: Any) -> Any:
        calls.append("blocked")
        raise AssertionError("deterministic MO contract smoke attempted external HTTP")

    remote_provider.httpx.request = reject_external_request
    try:
        yield calls
    finally:
        remote_provider.httpx.request = original


def _auth_headers() -> dict[str, str]:
    from nex_runtime import issue_mock_service_token

    token = issue_mock_service_token(service_id="nex-ag", audience="nex-mo")
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "11390000-0000-4000-8000-000000000001",
        "traceparent": "00-11390000000000000000000000000001-1139000000000001-01",
    }


def _schema_valid(root: Path, schema_name: str, payload: Any) -> bool:
    path = root / "contracts/schemas/service/nex_mo" / f"{schema_name}.v1.schema.json"
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return _validator_accepts(schema, payload)


def _root_schema(root: Path) -> dict[str, Any]:
    path = root / "contracts/openapi/nex-mo.openapi.yaml"
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return _mapping(_mapping(document.get("components")).get("schemas")).get(
        "ServiceRoot", {}
    )


def _validator_accepts(schema: Mapping[str, Any], payload: Any) -> bool:
    if not schema:
        return False
    return not list(Draft202012Validator(dict(schema)).iter_errors(payload))


@contextmanager
def _temporary_environment(values: Mapping[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value] if isinstance(value, list) and all(
        isinstance(item, Mapping) for item in value
    ) else []


def _int_list(value: Any) -> list[int]:
    return list(value) if isinstance(value, list) and all(
        isinstance(item, int) for item in value
    ) else []


def _nonnegative_int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    return (
        "mo_contract_http_smoke="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"auth={summary.get('unauthorized_rejection_count', 0)}/"
        f"{summary.get('protected_operation_count', 0)} "
        f"providers={summary.get('provider_success_count', 0)}/"
        f"{summary.get('provider_contract_count', 0)} "
        f"errors={summary.get('matched_error_count', 0)}/"
        f"{summary.get('error_case_count', 0)} "
        f"external={summary.get('external_request_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_contract_http_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
