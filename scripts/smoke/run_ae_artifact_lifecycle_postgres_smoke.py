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

import run_ae_artifact_collection_postgres_smoke as collection_pg  # noqa: E402
import run_ae_artifact_postgres_smoke as artifact_pg  # noqa: E402
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


SCHEMA_VERSION = "ae_artifact_lifecycle_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_ARTIFACT_LIFECYCLE_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_ARTIFACT_LIFECYCLE_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = artifact_pg.SERVICE_ID
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE


def run_ae_artifact_lifecycle_postgres_smoke(
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
        execution = _execute_ae_artifact_lifecycle_smoke(
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


def _execute_ae_artifact_lifecycle_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    tenant_id = f"tenant-artifact-lifecycle-{suffix}"
    workspace_id = f"workspace-artifact-lifecycle-{suffix}"
    owner_user_id = f"owner-artifact-lifecycle-{suffix}"
    artifact_ids: list[str] = []
    handoff_ids: list[str] = []
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        with tempfile.TemporaryDirectory(prefix="nex-ae-artifact-lifecycle-smoke-") as storage_dir:
            storage_root = Path(storage_dir) / "artifact-storage"
            with artifact_pg._temporary_env(
                "NEX_AE_ARTIFACT_STORAGE_ROOT",
                str(storage_root),
            ):
                app = build_service_app(SERVICE_SPECS[SERVICE_ID])
                app.state.nex_persistence = SimpleNamespace(
                    api_session_factory=session_factory
                )
                cx_client = artifact_pg.FakeCxArtifactSourceClient(
                    suffix=suffix,
                    request_id=request_id,
                    trace_id=trace_id,
                )
                register_artifact_handoff_routes(app, cx_client=cx_client)
                client = TestClient(app)
                headers = artifact_pg._auth_headers(
                    request_id=request_id,
                    trace_id=trace_id,
                )

                created = collection_pg._create_artifact(
                    client,
                    headers,
                    suffix=suffix,
                    label="lifecycle",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    render=True,
                )
                artifact_ids.append(created["artifact_id"])
                handoff_ids.append(created["artifact_handoff_id"])
                artifact_id = created["artifact_id"]

                archive = _post_lifecycle_action(
                    client,
                    headers,
                    artifact_id=artifact_id,
                    action="ARCHIVE",
                    idempotency_key=f"lifecycle-archive-{suffix}",
                )
                archived_readback = _get_artifact(client, headers, artifact_id)
                restore = _post_lifecycle_action(
                    client,
                    headers,
                    artifact_id=artifact_id,
                    action="RESTORE",
                    restore_status="READY",
                    idempotency_key=f"lifecycle-restore-{suffix}",
                )
                restored_readback = _get_artifact(client, headers, artifact_id)
                mark_deleted = _post_lifecycle_action(
                    client,
                    headers,
                    artifact_id=artifact_id,
                    action="MARK_DELETED",
                    idempotency_key=f"lifecycle-delete-{suffix}",
                )
                deleted_readback = _get_artifact(client, headers, artifact_id)
                deleted_collection = _get_collection(
                    client,
                    headers,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    status="DELETED",
                )
                ready_collection = _get_collection(
                    client,
                    headers,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    status="READY",
                )
                observations = _db_observations(
                    engine,
                    artifact_id=artifact_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                )
                materialized_file_count = _count_materialized_files(storage_root)
                checks = {
                    "archive_route_ok": archive["status_code"] == 200,
                    "archive_status": archive["body"].get("artifact_status")
                    == "ARCHIVED",
                    "archive_readback": archived_readback.get("artifact_status")
                    == "ARCHIVED",
                    "restore_route_ok": restore["status_code"] == 200,
                    "restore_status": restore["body"].get("artifact_status") == "READY",
                    "restore_readback": restored_readback.get("artifact_status")
                    == "READY",
                    "delete_route_ok": mark_deleted["status_code"] == 200,
                    "delete_status": mark_deleted["body"].get("artifact_status")
                    == "DELETED",
                    "delete_readback": deleted_readback.get("artifact_status")
                    == "DELETED",
                    "deleted_collection_ok": deleted_collection.get("count") == 1,
                    "ready_collection_empty": ready_collection.get("count") == 0,
                    "db_deleted_rows": observations["deleted_rows"] == 1,
                    "db_ready_rows": observations["ready_rows"] == 0,
                    "db_file_rows_retained": observations["file_rows"] >= 2,
                    "db_link_rows_retained": observations["link_rows"] >= 4,
                    "storage_files_retained": materialized_file_count >= 2,
                    "metadata_only_evidence": _metadata_only(
                        archive,
                        restore,
                        mark_deleted,
                        deleted_collection,
                        observations,
                        forbidden_fragments=[
                            database_url,
                            database_env,
                            "nuri1004",
                            str(storage_root),
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
                        "AE artifact lifecycle PostgreSQL smoke checks failed: "
                        f"{', '.join(failed_checks)}"
                    )
                cleanup = collection_pg._cleanup_smoke_rows(
                    engine,
                    artifact_ids=artifact_ids,
                    artifact_handoff_ids=handoff_ids,
                )
                return {
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "artifact_ids": artifact_ids,
                    "lifecycle": {
                        "archive_status": archive["body"]["artifact_status"],
                        "restore_status": restore["body"]["artifact_status"],
                        "delete_status": mark_deleted["body"]["artifact_status"],
                        "deleted_collection_count": deleted_collection["count"],
                        "ready_collection_count": ready_collection["count"],
                    },
                    "db_observations": observations,
                    "materialized_file_count": materialized_file_count,
                    "checks": checks,
                    "cleanup": cleanup,
                    "live_db": True,
                }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        collection_pg._cleanup_smoke_rows(
            engine,
            artifact_ids=artifact_ids,
            artifact_handoff_ids=handoff_ids,
        )
        engine.dispose()


def _post_lifecycle_action(
    client: TestClient,
    headers: dict[str, str],
    *,
    artifact_id: str,
    action: str,
    idempotency_key: str,
    restore_status: str | None = None,
) -> dict[str, Any]:
    payload = {"action": action}
    if restore_status is not None:
        payload["restore_status"] = restore_status
    response = client.post(
        f"/api/v1/artifacts/{artifact_id}/lifecycle-actions",
        json=payload,
        headers={**headers, "Idempotency-Key": idempotency_key},
    )
    return {"status_code": response.status_code, "body": response.json()}


def _get_artifact(
    client: TestClient,
    headers: dict[str, str],
    artifact_id: str,
) -> dict[str, Any]:
    response = client.get(f"/api/v1/artifacts/{artifact_id}", headers=headers)
    if response.status_code != 200:
        raise RuntimeError(f"artifact readback failed: {response.status_code}")
    return response.json()


def _get_collection(
    client: TestClient,
    headers: dict[str, str],
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    status: str,
) -> dict[str, Any]:
    response = client.get(
        "/api/v1/artifacts",
        params={
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "owner_user_id": owner_user_id,
            "status": status,
            "limit": "10",
        },
        headers=headers,
    )
    if response.status_code != 200:
        raise RuntimeError(f"artifact collection readback failed: {response.status_code}")
    return response.json()


def _db_observations(
    engine: Any,
    *,
    artifact_id: str,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
) -> dict[str, int]:
    with engine.connect() as connection:
        status_rows = {
            status.lower(): _scalar_count(
                connection,
                """
                SELECT count(*)
                FROM ae_artifacts
                WHERE tenant_id = :tenant_id
                  AND workspace_id = :workspace_id
                  AND owner_user_id = :owner_user_id
                  AND artifact_status = :status
                """,
                {
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "owner_user_id": owner_user_id,
                    "status": status,
                },
            )
            for status in ("READY", "ARCHIVED", "DELETED")
        }
        file_rows = _scalar_count(
            connection,
            """
            SELECT count(*)
            FROM ae_artifact_files
            WHERE artifact_id = :artifact_id
            """,
            {"artifact_id": artifact_id},
        )
        link_rows = _scalar_count(
            connection,
            """
            SELECT count(*)
            FROM ae_artifact_links
            WHERE artifact_file_id IN (
                SELECT artifact_file_id
                FROM ae_artifact_files
                WHERE artifact_id = :artifact_id
            )
            """,
            {"artifact_id": artifact_id},
        )
    return {
        "ready_rows": status_rows["ready"],
        "archived_rows": status_rows["archived"],
        "deleted_rows": status_rows["deleted"],
        "file_rows": file_rows,
        "link_rows": link_rows,
    }


def _scalar_count(connection: Any, sql: str, params: dict[str, str]) -> int:
    return int(connection.execute(text(sql), params).scalar() or 0)


def _count_materialized_files(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.rglob("*") if path.is_file())


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
            raise ValueError(f"AE artifact lifecycle smoke contains raw {key}.")
    if "nuri1004" in serialized_evidence:
        raise ValueError("AE artifact lifecycle smoke contains a database password.")
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError("AE artifact lifecycle smoke contains a local data path.")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ae_artifact_lifecycle_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_lifecycle_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"archive_status={evidence['lifecycle']['archive_status']} "
            f"restore_status={evidence['lifecycle']['restore_status']} "
            f"delete_status={evidence['lifecycle']['delete_status']} "
            f"deleted_count={evidence['lifecycle']['deleted_collection_count']} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"deleted_artifacts={evidence['cleanup']['artifacts']} "
            f"deleted_handoffs={evidence['cleanup']['handoffs']}"
        )
    return (
        "ae_artifact_lifecycle_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AE artifact lifecycle PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_artifact_lifecycle_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
