#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AE_PATH = ROOT / "services" / "nex-ae-api"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AE_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(SMOKE_PATH))

import run_ae_artifact_postgres_smoke as artifact_smoke  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifacts import register_artifact_handoff_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    load_env_file,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SCHEMA_VERSION = "ae_artifact_collection_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_ARTIFACT_COLLECTION_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_ARTIFACT_COLLECTION_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = artifact_smoke.SERVICE_ID
DEFAULT_PROFILE = artifact_smoke.DEFAULT_PROFILE
EXPECTED_COLLECTION_INDEXES = {
    "idx_ae_artifacts_owner_time",
    "idx_ae_artifacts_status_time",
    "ux_ae_artifacts_request",
}


def run_ae_artifact_collection_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
        }

    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
            env=env,
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        base_auth._require_test_database_url(database_url, env_name=database_env)
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_ae_artifact_collection_smoke(
            database_url=database_url,
            database_env=database_env,
        )
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile, env=env)
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        return _failure("execution_failed", detail, profile=profile, env=env)

    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "service_id": SERVICE_ID,
        "profile": profile,
        "database_env": database_env,
        "redacted_database_url": redact_database_url(database_url),
        "migration": {
            "planned": list(migration.planned),
            "applied": list(migration.applied),
            "skipped": list(migration.skipped),
        },
        **execution,
    }
    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _execute_ae_artifact_collection_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    tenant_id = f"tenant-artifact-library-{suffix}"
    workspace_id = f"workspace-artifact-library-{suffix}"
    owner_user_id = f"owner-artifact-library-{suffix}"
    artifact_ids: list[str] = []
    handoff_ids: list[str] = []
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        with tempfile.TemporaryDirectory(prefix="nex-ae-artifact-library-smoke-") as storage_dir:
            with artifact_smoke._temporary_env(
                "NEX_AE_ARTIFACT_STORAGE_ROOT",
                str(Path(storage_dir) / "artifact-storage"),
            ):
                app = build_service_app(SERVICE_SPECS[SERVICE_ID])
                app.state.nex_persistence = SimpleNamespace(
                    api_session_factory=session_factory
                )
                cx_client = artifact_smoke.FakeCxArtifactSourceClient(
                    suffix=suffix,
                    request_id=request_id,
                    trace_id=trace_id,
                )
                register_artifact_handoff_routes(app, cx_client=cx_client)
                client = TestClient(app)
                headers = artifact_smoke._auth_headers(
                    request_id=request_id,
                    trace_id=trace_id,
                )

                draft_artifact = _create_artifact(
                    client,
                    headers,
                    suffix=suffix,
                    label="draft",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    render=False,
                )
                ready_artifact = _create_artifact(
                    client,
                    headers,
                    suffix=suffix,
                    label="ready",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    render=True,
                )
                other_owner_artifact = _create_artifact(
                    client,
                    headers,
                    suffix=suffix,
                    label="other",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=f"{owner_user_id}-other",
                    render=False,
                )
                for created in (draft_artifact, ready_artifact, other_owner_artifact):
                    artifact_ids.append(created["artifact_id"])
                    handoff_ids.append(created["artifact_handoff_id"])

                collection = client.get(
                    "/api/v1/artifacts",
                    params={
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "owner_user_id": owner_user_id,
                        "limit": "10",
                    },
                    headers=headers,
                )
                ready_only = client.get(
                    "/api/v1/artifacts",
                    params={
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "owner_user_id": owner_user_id,
                        "status": "READY",
                        "limit": "10",
                    },
                    headers=headers,
                )
                limited = client.get(
                    "/api/v1/artifacts",
                    params={
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "owner_user_id": owner_user_id,
                        "limit": "1",
                    },
                    headers=headers,
                )
                missing_scope = client.get(
                    "/api/v1/artifacts",
                    params={"tenant_id": tenant_id},
                    headers=headers,
                )
                observations = _db_observations(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    other_owner_user_id=f"{owner_user_id}-other",
                )
                checks = {
                    "collection_route_ok": collection.status_code == 200,
                    "collection_count": collection.json().get("count") == 2,
                    "collection_order_latest_first": [
                        item["artifact_id"] for item in collection.json()["items"]
                    ]
                    == [ready_artifact["artifact_id"], draft_artifact["artifact_id"]],
                    "ready_filter_ok": ready_only.status_code == 200
                    and ready_only.json().get("count") == 1
                    and ready_only.json()["items"][0]["artifact_status"] == "READY",
                    "limit_ok": limited.status_code == 200
                    and limited.json().get("count") == 1,
                    "owner_scope_excludes_other": all(
                        item["owner_user_id"] == owner_user_id
                        for item in collection.json()["items"]
                    ),
                    "missing_scope_rejected": missing_scope.status_code == 422,
                    "db_owner_rows": observations["owner_rows"] == 2,
                    "db_ready_rows": observations["ready_rows"] == 1,
                    "db_other_owner_rows": observations["other_owner_rows"] == 1,
                    "indexes_present": observations["indexes_present"]
                    == sorted(EXPECTED_COLLECTION_INDEXES),
                    "metadata_only_collection": _metadata_only(
                        collection.json(),
                        ready_only.json(),
                        limited.json(),
                        forbidden_fragments=[
                            database_url,
                            database_env,
                            "nuri1004",
                            str(storage_dir),
                            "/data/nex-platform",
                            "storage_ref",
                            "content_base64",
                            "rendered_payloads",
                        ],
                    ),
                }
                failed_checks = [key for key, passed in checks.items() if not passed]
                if failed_checks:
                    raise RuntimeError(
                        "AE artifact collection PostgreSQL smoke checks failed: "
                        f"{', '.join(failed_checks)}"
                    )
                cleanup = _cleanup_smoke_rows(
                    engine,
                    artifact_ids=artifact_ids,
                    artifact_handoff_ids=handoff_ids,
                )
                return {
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "artifact_ids": artifact_ids,
                    "collection": {
                        "count": collection.json()["count"],
                        "ready_count": ready_only.json()["count"],
                        "limited_count": limited.json()["count"],
                        "statuses": [
                            item["artifact_status"] for item in collection.json()["items"]
                        ],
                        "downloadable_formats": [
                            item["downloadable_formats"]
                            for item in collection.json()["items"]
                        ],
                    },
                    "db_observations": observations,
                    "checks": checks,
                    "cleanup": cleanup,
                    "live_db": True,
                }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        _cleanup_smoke_rows(
            engine,
            artifact_ids=artifact_ids,
            artifact_handoff_ids=handoff_ids,
        )
        engine.dispose()


def _create_artifact(
    client: TestClient,
    headers: dict[str, str],
    *,
    suffix: str,
    label: str,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    render: bool,
) -> dict[str, str]:
    handoff_response = client.post(
        "/api/v1/artifact-handoffs",
        json=_artifact_handoff_payload(
            suffix=suffix,
            label=label,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        ),
        headers={**headers, "Idempotency-Key": f"handoff-{label}-{suffix}"},
    )
    if handoff_response.status_code != 200:
        raise RuntimeError(f"artifact handoff route failed: {label}")
    handoff = handoff_response.json()
    artifact_response = client.post(
        "/api/v1/artifacts",
        json={
            "artifact_handoff_id": handoff["artifact_handoff_id"],
            "display_title": f"Artifact Library {label.title()} {suffix}",
        },
        headers={**headers, "Idempotency-Key": f"artifact-{label}-{suffix}"},
    )
    if artifact_response.status_code != 200:
        raise RuntimeError(f"artifact create route failed: {label}")
    artifact = artifact_response.json()
    if render:
        render_response = client.post(
            f"/api/v1/artifacts/{artifact['artifact_id']}/render-jobs",
            json={"target_formats": ["MD", "HTML_PREVIEW"]},
            headers={**headers, "Idempotency-Key": f"render-{label}-{suffix}"},
        )
        if render_response.status_code != 200:
            raise RuntimeError(f"artifact render route failed: {label}")
        artifact = render_response.json()["artifact"]
    return {
        "artifact_handoff_id": handoff["artifact_handoff_id"],
        "artifact_id": artifact["artifact_id"],
    }


def _artifact_handoff_payload(
    *,
    suffix: str,
    label: str,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
) -> dict[str, Any]:
    return {
        **artifact_smoke._artifact_handoff_payload(suffix),
        "chat_document_id": f"chat-doc-artifact-library-{label}-{suffix}",
        "interaction_id": f"interaction-artifact-library-{label}-{suffix}",
        "workspace_id": workspace_id,
        "tenant_id": tenant_id,
        "owner_user_id": owner_user_id,
        "artifact_title": f"Artifact Library {label.title()} {suffix}",
        "actor_claims_ref": {
            "actor_type": "user",
            "actor_id": owner_user_id,
            "tenant_id": tenant_id,
        },
    }


def _db_observations(
    engine: Any,
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    other_owner_user_id: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        owner_rows = _scalar_count(
            connection,
            """
            SELECT count(*)
            FROM ae_artifacts
            WHERE tenant_id = :tenant_id
              AND workspace_id = :workspace_id
              AND owner_user_id = :owner_user_id
            """,
            {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
            },
        )
        ready_rows = _scalar_count(
            connection,
            """
            SELECT count(*)
            FROM ae_artifacts
            WHERE tenant_id = :tenant_id
              AND workspace_id = :workspace_id
              AND owner_user_id = :owner_user_id
              AND artifact_status = 'READY'
            """,
            {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
            },
        )
        other_owner_rows = _scalar_count(
            connection,
            """
            SELECT count(*)
            FROM ae_artifacts
            WHERE tenant_id = :tenant_id
              AND workspace_id = :workspace_id
              AND owner_user_id = :owner_user_id
            """,
            {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "owner_user_id": other_owner_user_id,
            },
        )
        indexes = (
            connection.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = 'ae_artifacts'
                    ORDER BY indexname
                    """
                )
            )
            .scalars()
            .all()
        )
    return {
        "owner_rows": owner_rows,
        "ready_rows": ready_rows,
        "other_owner_rows": other_owner_rows,
        "indexes_present": sorted(set(indexes).intersection(EXPECTED_COLLECTION_INDEXES)),
    }


def _scalar_count(connection: Any, sql: str, params: dict[str, str]) -> int:
    return int(connection.execute(text(sql), params).scalar() or 0)


def _cleanup_smoke_rows(
    engine: Any,
    *,
    artifact_ids: list[str],
    artifact_handoff_ids: list[str],
) -> dict[str, int]:
    deleted = {"artifacts": 0, "handoffs": 0}
    try:
        with engine.begin() as connection:
            for artifact_id in artifact_ids:
                result = connection.execute(
                    text("DELETE FROM ae_artifacts WHERE artifact_id = :artifact_id"),
                    {"artifact_id": artifact_id},
                )
                deleted["artifacts"] += int(result.rowcount or 0)
            for artifact_handoff_id in artifact_handoff_ids:
                result = connection.execute(
                    text(
                        """
                        DELETE FROM ae_artifact_handoffs
                        WHERE artifact_handoff_id = :artifact_handoff_id
                        """
                    ),
                    {"artifact_handoff_id": artifact_handoff_id},
                )
                deleted["handoffs"] += int(result.rowcount or 0)
    except SQLAlchemyError:
        return deleted
    return deleted


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    env: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": _safe_detail(detail, env),
    }


def _metadata_only(*payloads: Any, forbidden_fragments: list[str]) -> bool:
    serialized = json.dumps(payloads, ensure_ascii=False, sort_keys=True, default=str)
    return all(fragment not in serialized for fragment in forbidden_fragments)


def _safe_detail(detail: str, env: Mapping[str, str]) -> str:
    safe = detail
    for key in (
        service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE),
        "NEX_AE_ARTIFACT_STORAGE_ROOT",
    ):
        value = env.get(key)
        if value:
            safe = safe.replace(value, f"<redacted:{key}>")
    return safe.replace("nuri1004", "***")


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    for key in (
        service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE),
        "NEX_AE_ARTIFACT_STORAGE_ROOT",
    ):
        value = environ.get(key)
        if value and value in serialized_evidence:
            raise ValueError(f"AE artifact collection smoke contains raw {key}.")
    if "nuri1004" in serialized_evidence:
        raise ValueError("AE artifact collection smoke contains a database password.")
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError("AE artifact collection smoke contains a local data path.")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ae_artifact_collection_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_collection_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"collection_count={evidence['collection']['count']} "
            f"ready_count={evidence['collection']['ready_count']} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"deleted_artifacts={evidence['cleanup']['artifacts']} "
            f"deleted_handoffs={evidence['cleanup']['handoffs']}"
        )
    return (
        "ae_artifact_collection_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AE artifact collection PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_artifact_collection_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
