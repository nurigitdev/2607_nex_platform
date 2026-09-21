#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.pgvector_store import build_pgvector_cx_vector_store  # noqa: E402
from nex_cx.vector_index_freshness import (  # noqa: E402
    build_embedding_profile,
    build_source_snapshot,
    build_vector_index_manifest,
)
from nex_cx.vector_index_operations import (  # noqa: E402
    CX_VECTOR_INDEX_RECONCILED_EVENT,
    register_vector_index_operations_routes,
)
from nex_cx.vector_index_publish import publish_vector_index  # noqa: E402
from nex_cx.vector_index_repository import (  # noqa: E402
    SqlAlchemyVectorIndexRepository,
)
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    redact_database_url,
)
from run_cx_pgvector_adapter_postgres_smoke import (  # noqa: E402
    _digest,
    _seed_fixture,
)
from run_migrations import (  # noqa: E402
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SCHEMA_VERSION = "cx_vector_readiness_api_postgres_smoke.v1"
SMOKE_ENV = "NEX_CX_VECTOR_READINESS_API_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_CX_VECTOR_READINESS_API_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"


def run_cx_vector_readiness_api_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure("profile_not_allowed", f"{PROFILE_ENV} must be test.")
    database_url = ""
    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        if not _target_url_allowed(database_url):
            return _failure("target_not_allowed", "CX test database target is required.")
        migration = run_service_migrations(
            SERVICE_ID, database_url=database_url, profile=profile
        )
        execution = _execute_smoke(
            database_url,
            environ={**env, database_env: database_url},
            database_env=database_env,
        )
        if execution["failed_checks"]:
            return _failure(
                "readiness_api_smoke_failed",
                execution["failed_checks"],
                execution=execution,
            )
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "profile": profile,
            "redacted_database_url": redact_database_url(database_url),
            "migration_applied": list(migration.applied),
            "remote_embedding_required": False,
            **execution,
        }
    except Exception as exc:  # pragma: no cover - protected PostgreSQL evidence
        return _failure(
            "execution_failed",
            exc.__class__.__name__,
            redacted_database_url=(
                redact_database_url(database_url) if database_url else None
            ),
        )


def _execute_smoke(  # pragma: no cover - protected PostgreSQL evidence
    database_url: str,
    *,
    environ: Mapping[str, str],
    database_env: str,
) -> dict[str, Any]:
    ids = SimpleNamespace(
        source=uuid4(),
        content=uuid4(),
        upload=uuid4(),
        artifact=uuid4(),
        chunk_set=uuid4(),
        chunk=uuid4(),
    )
    now = datetime.now(UTC)
    source_hash = _digest(f"source:{ids.content}")
    markdown_hash = _digest(f"markdown:{ids.content}")
    source = build_source_snapshot(
        chunk_set_id=str(ids.chunk_set),
        chunk_policy_id="1000_100",
        source_markdown_sha256=markdown_hash,
        chunks=[{
            "chunk_id": str(ids.chunk),
            "ordinal": 0,
            "text_sha256": _digest(f"chunk:{ids.chunk}"),
        }],
    )
    profile = build_embedding_profile(
        provider_alias="mock-s94",
        model_profile_id="Qwen3-Embedding-4B",
        model_revision="bf16",
        deployment_id="mock-local",
        vector_dimension=2560,
    )
    manifest = build_vector_index_manifest(
        content_object_id=str(ids.content),
        tenant_ref={"type": "oa.tenant", "id": "s94-adapter-tenant"},
        owner_subject_ref={"type": "oa.user", "id": "s94-adapter-owner"},
        source_snapshot=source,
        embedding_profile=profile,
        trace_id="s94-adapter-trace",
        request_id="s94-adapter-request",
        observed_at=now.isoformat(),
    )
    checks: dict[str, bool] = {}
    engine = None
    with psycopg.connect(database_url, autocommit=True) as connection:
        _seed_fixture(
            connection,
            ids=ids,
            manifest=manifest,
            source_hash=source_hash,
            markdown_hash=markdown_hash,
            observed_at=now,
        )
        try:
            engine = build_engine(database_url)
            repository = SqlAlchemyVectorIndexRepository(build_session_factory(engine))
            adapter = build_pgvector_cx_vector_store(
                database_env=database_env,
                environ=environ,
                workload="worker",
            )
            context = CxAccessContext(
                caller_service_id="nex-cx",
                tenant_id="s94-adapter-tenant",
                subject_id="s94-adapter-owner",
                request_id="s94-readiness-request",
                trace_id="93800000000000000000000000000001",
                scopes=("service:call",),
            )
            vector = tuple([1.0] + ([0.0] * 2559))
            ready = publish_vector_index(
                access_context=context,
                manifest=manifest,
                vectors_by_chunk_id={str(ids.chunk): vector},
                vector_store=adapter,
                repository=repository,
                observed_at=(now + timedelta(seconds=1)).isoformat(),
            )
            event_store = InMemoryOperationalEventStore()
            app = build_service_app(SERVICE_SPECS["nex-cx"])
            register_vector_index_operations_routes(
                app,
                repository=repository,
                vector_store=adapter,
                event_emitter=OperationalEventEmitter(
                    service_id="nex-cx", store=event_store
                ),
            )
            client = TestClient(app)
            headers = _headers(
                tenant_id=context.tenant_id,
                owner_subject_id=context.subject_id,
            )
            path = f"/api/v1/vector-indexes/{ready['vector_index_id']}/readiness"
            fresh = client.get(path, headers=headers)
            hidden = client.get(
                path,
                headers=_headers(
                    tenant_id=context.tenant_id,
                    owner_subject_id="other-owner",
                ),
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM cx_vectors WHERE vector_index_id = %s",
                    (ready["vector_index_id"],),
                )
            drift = client.get(path, headers=headers)
            reconciled = client.post(
                f"{path}/reconcile",
                headers=headers,
                json={
                    "source_snapshot": source,
                    "embedding_profile": profile,
                    "observed_at": (now + timedelta(seconds=2)).isoformat(),
                },
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT status, checkpoint_version FROM cx_vector_indexes "
                    "WHERE vector_index_id = %s",
                    (ready["vector_index_id"],),
                )
                persisted = cursor.fetchone()
            events = event_store.list_events(
                event_type=CX_VECTOR_INDEX_RECONCILED_EVENT
            )
            fresh_body = fresh.json()
            drift_body = drift.json()
            reconcile_body = reconciled.json()
            checks.update(
                {
                    "fresh_readiness": fresh.status_code == 200
                    and fresh_body["retrieval_usable"] is True,
                    "owner_isolation": hidden.status_code == 404,
                    "read_is_non_mutating": drift.status_code == 200
                    and drift_body["status"] == "READY"
                    and drift_body["checkpoint_version"] == 1,
                    "payload_drift_visible": drift_body["freshness_status"] == "STALE"
                    and drift_body["freshness_reason"]
                    == "PAYLOAD_COUNT_MISMATCH",
                    "reconcile_persisted": reconciled.status_code == 200
                    and reconcile_body["status"] == "REBUILD_REQUIRED"
                    and persisted == ("REBUILD_REQUIRED", 3),
                    "reconcile_action": reconcile_body["action"] == "ADMIT_REBUILD",
                    "event_emitted": len(events) == 1
                    and reconcile_body["observability"]["ok"] is True,
                    "event_metadata_only": len(events) == 1
                    and "source_markdown_sha256" not in str(events[0]).lower()
                    and "embedding_sha256" not in str(events[0]).lower(),
                    "primary_fallback_route": adapter.uses_primary_database,
                }
            )
        finally:
            if engine is not None:
                engine.dispose()
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM cx_vectors WHERE vector_index_id = %s",
                    (manifest["vector_index_id"],),
                )
                cursor.execute(
                    "DELETE FROM cx_content_objects WHERE content_object_id = %s",
                    (ids.content,),
                )
                cursor.execute(
                    "DELETE FROM cx_source_files WHERE source_file_id = %s",
                    (ids.source,),
                )
                cursor.execute(
                    "SELECT count(*) FROM cx_vector_indexes WHERE vector_index_id = %s",
                    (manifest["vector_index_id"],),
                )
                checks["cleanup_complete"] = cursor.fetchone() == (0,)
    return {
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "check_count": len(checks),
        "vector_dimension": 2560,
        "api_boundary": "owner_scoped_readiness_and_explicit_reconciliation",
    }


def _headers(*, tenant_id: str, owner_subject_id: str) -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-ag", audience="nex-cx")
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-NEX-Tenant-ID": tenant_id,
        "X-NEX-Subject-ID": owner_subject_id,
        "X-Request-ID": "request-0938",
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    }


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    return (
        unquote(parsed.username or "") == EXPECTED_ROLE
        and parsed.path.lstrip("/") == EXPECTED_DATABASE
    )


def _failure(code: str, detail: Any, **extra: Any) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "error": {"code": code, "detail": detail},
        **extra,
    }


def _summary(result: Mapping[str, Any]) -> str:
    status = str(result["status"]).lower()
    if status == "skipped":
        return f"cx_vector_readiness_api_postgres_smoke=skipped reason={SMOKE_ENV}"
    if status == "pass":
        return (
            "cx_vector_readiness_api_postgres_smoke=pass "
            f"checks={result['check_count']}/{result['check_count']} "
            "remote_required=False"
        )
    return f"cx_vector_readiness_api_postgres_smoke=fail error={result['error']['code']}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_vector_readiness_api_postgres_smoke()
    print(_summary(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
