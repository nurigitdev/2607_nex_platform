#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import sys
from typing import Any, Protocol
from unittest.mock import patch

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_mo.main import PROVIDER_READINESS, app  # noqa: E402
from nex_runtime import issue_mock_service_token, redact_database_url  # noqa: E402
from run_protected_dgx_live_profile import (  # noqa: E402
    protected_dgx_vllm_profile_defaults,
)


SCHEMA_VERSION = "mo_provider_readiness_live_postgres_smoke.v1"
ACTIVATION_ENV = "NEX_MO_PROVIDER_READINESS_LIVE_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_MO_PROVIDER_READINESS_LIVE_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
EXPECTED_DATABASE = "nex_mo_test"
EXPECTED_ROLE = "nex_mo_user"
PROVIDER_SCHEMA_PATH = (
    ROOT / "contracts/schemas/service/nex_mo/provider_readiness.v1.schema.json"
)
PROTECTED_ENV_KEYS = (
    "NEX_MO_TEST_DATABASE_URL",
    "NEX_MO_DATABASE_URL",
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_MODELS_URL",
    "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
    "NEX_MO_VLLM_API_KEY",
)
REQUIRED_PROVIDER_ENDPOINTS = (
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_RERANKER_URL",
)


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class HttpClient(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse: ...


ClientFactory = Callable[[], HttpClient]


def run_mo_provider_readiness_live_postgres_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    client_factory: ClientFactory | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ACTIVATION_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1130",
            "requirement": "S113",
            "status": "SKIPPED",
            "skip_reason": f"{ACTIVATION_ENV} is not enabled.",
        }

    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure(
            "profile_not_allowed",
            profile=profile,
            diagnostics={"expected_profile": DEFAULT_PROFILE},
        )

    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_PROVIDER_READINESS_TTL_SECONDS": env.get(
            "NEX_MO_PROVIDER_READINESS_TTL_SECONDS", "60"
        ),
    }
    database_url = effective_env.get("NEX_MO_TEST_DATABASE_URL", "").strip()
    missing = _missing_configuration(effective_env, database_url=database_url)
    if missing:
        return _failure(
            "configuration_invalid",
            profile=profile,
            diagnostics={"missing_env": missing},
        )
    effective_env["NEX_MO_DATABASE_URL"] = database_url

    try:
        token = issue_mock_service_token(service_id="nex-ag", audience="nex-mo")
        headers = {"Authorization": f"Bearer {token.access_token}"}
        factory = client_factory or (lambda: TestClient(app))
        with patch.dict(os.environ, effective_env, clear=True):
            PROVIDER_READINESS.clear()
            client = factory()
            unauthorized = client.get("/api/v1/provider-route-health")
            ready = client.get("/ready")
            route_health = client.get(
                "/api/v1/provider-route-health",
                headers=headers,
            )
        PROVIDER_READINESS.clear()

        ready_payload = _json_object(ready)
        route_payload = _json_object(route_health)
        provider_check = _provider_check(ready_payload)
        database_check = _database_check(ready_payload)
        Draft202012Validator(
            json.loads(PROVIDER_SCHEMA_PATH.read_text(encoding="utf-8"))
        ).validate(provider_check)
        Draft202012Validator(
            json.loads(PROVIDER_SCHEMA_PATH.read_text(encoding="utf-8"))
        ).validate(route_payload)

        capabilities = [
            route.get("provider_capability")
            for route in route_payload.get("routes", [])
            if isinstance(route, Mapping)
        ]
        models = {
            str(route.get("provider_capability")): str(route.get("model_revision"))
            for route in route_payload.get("routes", [])
            if isinstance(route, Mapping)
        }
        latency_ms = {
            str(route.get("provider_capability")): route.get("latency_ms")
            for route in route_payload.get("routes", [])
            if isinstance(route, Mapping)
        }
        checks = {
            "unauthorized_route_rejected": unauthorized.status_code == 401,
            "ready_route_succeeded": ready.status_code == 200,
            "route_health_query_succeeded": route_health.status_code == 200,
            "actual_test_database_identity": (
                database_check.get("ok") is True
                and database_check.get("database_name") == EXPECTED_DATABASE
                and database_check.get("database_user") == EXPECTED_ROLE
            ),
            "provider_readiness_ready": (
                provider_check.get("ok") is True
                and provider_check.get("provider_mode") == "live"
                and provider_check.get("readiness_status") == "READY"
            ),
            "three_active_preflights_ready": (
                capabilities == ["embedding", "reranking", "generation"]
                and route_payload.get("summary", {})
                .get("status_counts", {})
                .get("READY")
                == 3
                and all(
                    route.get("source") == "active_preflight"
                    and route.get("status") == "READY"
                    for route in route_payload.get("routes", [])
                    if isinstance(route, Mapping)
                )
            ),
            "readiness_snapshot_reused": (
                provider_check.get("checked_at") == route_payload.get("checked_at")
                and provider_check.get("expires_at") == route_payload.get("expires_at")
                and route_payload.get("cache_status") == "FRESH"
            ),
            "provider_contract_valid": True,
        }
        passed = all(checks.values())
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1130",
            "requirement": "S113",
            "status": "PASS" if passed else "FAIL",
            "failure_code": (
                None if passed else "mo_provider_readiness_live_smoke_failed"
            ),
            "service_id": "nex-mo",
            "profile": profile,
            "redacted_database_url": redact_database_url(database_url),
            "database_identity": {
                "database_name": database_check.get("database_name"),
                "database_user": database_check.get("database_user"),
                "latency_ms": database_check.get("latency_ms"),
            },
            "provider_mode": route_payload.get("provider_mode"),
            "provider_models": models,
            "provider_latency_ms": latency_ms,
            "cache_status": route_payload.get("cache_status"),
            "checks": checks,
            "summary": {
                "passed_check_count": sum(checks.values()),
                "check_count": len(checks),
                "ready_provider_count": route_payload.get("summary", {})
                .get("status_counts", {})
                .get("READY", 0),
                "unauthorized_status": unauthorized.status_code,
                "ready_status": ready.status_code,
                "route_health_status": route_health.status_code,
            },
            "migration": {
                "required": False,
                "reason": "read_only_readiness_smoke",
            },
            "redaction": {
                "status": "PASS",
                "excluded": [
                    "provider_endpoint",
                    "provider_api_key",
                    "database_password",
                    "request_payload",
                    "response_payload",
                ],
            },
            "next_slice": "1131" if passed else None,
        }
        assert_evidence_redacted(evidence, effective_env)
        return evidence
    except Exception as exc:
        PROVIDER_READINESS.clear()
        failure = _failure(
            "live_execution_failed",
            profile=profile,
            diagnostics={"exception_type": exc.__class__.__name__},
        )
        assert_evidence_redacted(failure, effective_env)
        return failure


def _missing_configuration(
    env: Mapping[str, str],
    *,
    database_url: str,
) -> list[str]:
    missing = []
    if not database_url:
        missing.append("NEX_MO_TEST_DATABASE_URL")
    missing.extend(key for key in REQUIRED_PROVIDER_ENDPOINTS if not env.get(key))
    if not (env.get("NEX_MO_VLLM_MODELS_URL") or env.get("NEX_MO_VLLM_BASE_URL")):
        missing.append("NEX_MO_VLLM_MODELS_URL|NEX_MO_VLLM_BASE_URL")
    return missing


def _json_object(response: HttpResponse) -> dict[str, Any]:
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("response_not_json_object")
    return payload


def _database_check(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    checks = payload.get("checks")
    if not isinstance(checks, list) or not checks or not isinstance(checks[0], Mapping):
        raise ValueError("database_readiness_check_missing")
    return checks[0]


def _provider_check(payload: Mapping[str, Any]) -> dict[str, Any]:
    checks = payload.get("checks")
    if not isinstance(checks, list) or len(checks) < 2 or not isinstance(
        checks[1], Mapping
    ):
        raise ValueError("provider_readiness_check_missing")
    return dict(checks[1])


def _failure(
    failure_code: str,
    *,
    profile: str | None = None,
    diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1130",
        "requirement": "S113",
        "status": "FAIL",
        "failure_code": failure_code,
        "issues": [failure_code],
        "next_slice": None,
    }
    if profile is not None:
        evidence["profile"] = profile
    if diagnostics:
        evidence["diagnostics"] = dict(diagnostics)
    return evidence


def assert_evidence_redacted(
    evidence: Mapping[str, Any],
    environ: Mapping[str, str],
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    protected_values = [
        str(environ.get(key) or "") for key in PROTECTED_ENV_KEYS
    ]
    database_url = str(environ.get("NEX_MO_TEST_DATABASE_URL") or "")
    if database_url:
        try:
            protected_values.append(str(make_url(database_url).password or ""))
        except Exception:
            pass
    leaked = [
        value for value in protected_values if len(value) >= 6 and value in serialized
    ]
    if leaked:
        raise ValueError("MO provider readiness smoke evidence contains protected value")


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary")
    if not isinstance(summary, Mapping):
        summary = {}
    return (
        "mo_provider_readiness_live_postgres_smoke="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"providers={summary.get('ready_provider_count', 0)}/3 "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_readiness_live_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
