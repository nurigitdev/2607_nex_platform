#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any, Mapping

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

import nex_mo.remote_provider as remote_provider  # noqa: E402
from nex_mo.provider_telemetry_repository import (  # noqa: E402
    SqlAlchemyDurableProviderTelemetryRepository,
)
from nex_mo.provider_telemetry_store import DurableProviderTelemetryStore  # noqa: E402
from nex_mo.providers import register_mock_provider_routes  # noqa: E402
from nex_runtime import issue_mock_service_token  # noqa: E402
from run_mo_provider_telemetry_restart_concurrency import (  # noqa: E402
    _apply_sqlite_migration,
)


def run_mo_provider_telemetry_durable_api() -> dict[str, Any]:
    env = {
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://private-provider/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "private-smoke-key",
        "NEX_MO_REMOTE_EMBEDDING_MODEL": "EmbeddingRuntime",
        "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION": "embedding-revision-a",
        "NEX_MO_REMOTE_EMBEDDING_DEPLOYMENT_ID": "embedding-deployment-a",
    }
    prior_env = {key: os.environ.get(key) for key in env}
    prior_store = remote_provider.current_remote_provider_telemetry_store()
    try:
        os.environ.update(env)
        with TemporaryDirectory(prefix="nex-mo-telemetry-api-") as directory:
            engine = create_engine(
                f"sqlite+pysqlite:///{Path(directory) / 'telemetry.db'}"
            )
            _apply_sqlite_migration(engine)
            factory = sessionmaker(
                bind=engine,
                autoflush=False,
                expire_on_commit=False,
            )
            config = remote_provider.build_remote_embedding_execution_config(env)
            first = DurableProviderTelemetryStore(
                SqlAlchemyDurableProviderTelemetryRepository(factory)
            )
            first.record_success(
                config,
                latency_ms=17,
                observed_at="2026-09-30T01:00:00Z",
            )
            restarted = DurableProviderTelemetryStore(
                SqlAlchemyDurableProviderTelemetryRepository(factory)
            )
            remote_provider.configure_remote_provider_telemetry_store(restarted)
            app = FastAPI()
            register_mock_provider_routes(app)
            client = TestClient(app)
            token = issue_mock_service_token(
                service_id="nex-ag",
                audience="nex-mo",
            )
            unauthorized = client.get("/api/v1/provider-telemetry")
            response = client.get(
                "/api/v1/provider-telemetry",
                params={"capability": "embedding"},
                headers={"Authorization": f"Bearer {token.access_token}"},
            )
            payload = response.json()
            serialized = json.dumps(payload, sort_keys=True)
            deleted = restarted._repository.clear()
            engine.dispose()
    finally:
        remote_provider.configure_remote_provider_telemetry_store(prior_store)
        for key, value in prior_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    item = payload.get("data", [{}])[0] if response.status_code == 200 else {}
    checks = {
        "service_claim_required": unauthorized.status_code == 401,
        "authenticated_read_succeeded": response.status_code == 200,
        "restart_value_recovered": item.get("request_count") == 1
        and item.get("success_count") == 1,
        "wire_schema_preserved": payload.get("meta", {}).get("schema_version")
        == "mo_provider_telemetry_snapshot.v1"
        and len(item) == 26,
        "private_runtime_values_redacted": "private-provider" not in serialized
        and "private-smoke-key" not in serialized,
        "cleanup_removed_evidence": deleted == 1,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_provider_telemetry_durable_api_smoke.v1",
        "slice": "1158",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "unauthorized_status": unauthorized.status_code,
            "authenticated_status": response.status_code,
            "wire_field_count": len(item),
            "request_count": item.get("request_count", 0),
            "cleanup_count": deleted,
        },
        "next_slice": "1159" if passed else None,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_telemetry_durable_api="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"unauthorized={summary.get('unauthorized_status', 0)} "
        f"authenticated={summary.get('authenticated_status', 0)} "
        f"fields={summary.get('wire_field_count', 0)} "
        f"requests={summary.get('request_count', 0)} "
        f"cleanup={summary.get('cleanup_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_telemetry_durable_api()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
