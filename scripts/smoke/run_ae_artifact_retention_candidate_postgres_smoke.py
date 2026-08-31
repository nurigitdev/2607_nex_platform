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
from urllib.parse import unquote, urlsplit
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


SCHEMA_VERSION = "ae_artifact_retention_candidate_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_ARTIFACT_RETENTION_CANDIDATE_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_ARTIFACT_RETENTION_CANDIDATE_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = artifact_pg.SERVICE_ID
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
AS_OF = "2026-09-01T00:00:00Z"
OLD_LOGICAL_PURGE_AT = "2026-07-31T00:00:00Z"
RECENT_LOGICAL_PURGE_AT = "2026-08-30T00:00:00Z"


def run_ae_artifact_retention_candidate_postgres_smoke(
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
        execution = _execute_ae_artifact_retention_candidate_smoke(
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


def _execute_ae_artifact_retention_candidate_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    tenant_id = f"tenant-artifact-retention-{suffix}"
    workspace_id = f"workspace-artifact-retention-{suffix}"
    owner_user_id = f"owner-artifact-retention-{suffix}"
    artifact_ids: list[str] = []
    handoff_ids: list[str] = []
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        with tempfile.TemporaryDirectory(prefix="nex-ae-artifact-retention-smoke-") as storage_dir:
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

                old_deleted = _create_rendered_deleted_artifact(
                    client,
                    headers,
                    engine=engine,
                    suffix=suffix,
                    label="old",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    logical_purged_at=OLD_LOGICAL_PURGE_AT,
                )
                recent_deleted = _create_rendered_deleted_artifact(
                    client,
                    headers,
                    engine=engine,
                    suffix=suffix,
                    label="recent",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    logical_purged_at=RECENT_LOGICAL_PURGE_AT,
                )
                for created in (old_deleted, recent_deleted):
                    artifact_ids.append(created["artifact_id"])
                    handoff_ids.append(created["artifact_handoff_id"])

                candidates = client.get(
                    "/api/v1/artifact-retention/candidates",
                    params={
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "owner_user_id": owner_user_id,
                        "retention_days": "30",
                        "as_of": AS_OF,
                        "limit": "10",
                    },
                    headers=headers,
                )
                observations = _db_observations(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    cutoff_at="2026-08-02T00:00:00Z",
                )
                materialized_file_count = collection_pg._count_materialized_files(
                    storage_root
                ) if hasattr(collection_pg, "_count_materialized_files") else _count_files(
                    storage_root
                )
                payload = candidates.json() if candidates.status_code == 200 else {}
                checks = {
                    "candidate_route_ok": candidates.status_code == 200,
                    "candidate_count": payload.get("count") == 1,
                    "candidate_matches_old_deleted": _candidate_ids(payload)
                    == [old_deleted["artifact_id"]],
                    "candidate_policy_dry_run": payload.get("metadata", {}).get(
                        "dry_run"
                    )
                    is True,
                    "candidate_no_physical_delete": payload.get("metadata", {}).get(
                        "physical_delete_executed"
                    )
                    is False,
                    "db_candidate_rows": observations["candidate_rows"] == 1,
                    "db_deleted_rows_retained": observations["deleted_rows"] == 2,
                    "db_artifact_rows_retained": observations["artifact_rows"] == 2,
                    "db_file_rows_retained": observations["file_rows"] >= 4,
                    "db_link_rows_retained": observations["link_rows"] >= 8,
                    "storage_files_retained": materialized_file_count >= 4,
                    "metadata_only_evidence": _metadata_only(
                        payload,
                        observations,
                        forbidden_fragments=[
                            database_url,
                            database_env,
                            _database_url_password(database_url),
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
                        "AE artifact retention candidate PostgreSQL smoke checks "
                        f"failed: {', '.join(failed_checks)}"
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
                    "retention": {
                        "as_of": AS_OF,
                        "retention_days": 30,
                        "cutoff_at": payload["filter"]["cutoff_at"],
                        "candidate_count": payload["count"],
                        "candidate_artifact_ids": _candidate_ids(payload),
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


def _create_rendered_deleted_artifact(
    client: TestClient,
    headers: dict[str, str],
    *,
    engine: Any,
    suffix: str,
    label: str,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    logical_purged_at: str,
) -> dict[str, str]:
    created = collection_pg._create_artifact(
        client,
        headers,
        suffix=suffix,
        label=f"retention-{label}",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        render=True,
    )
    lifecycle = client.post(
        f"/api/v1/artifacts/{created['artifact_id']}/lifecycle-actions",
        json={"action": "MARK_DELETED", "reason_code": "retention_smoke"},
        headers={**headers, "Idempotency-Key": f"retention-delete-{label}-{suffix}"},
    )
    if lifecycle.status_code != 200:
        raise RuntimeError(f"artifact logical delete route failed: {label}")
    _set_artifact_updated_at(
        engine,
        artifact_id=created["artifact_id"],
        updated_at=logical_purged_at,
    )
    return created


def _set_artifact_updated_at(
    engine: Any,
    *,
    artifact_id: str,
    updated_at: str,
) -> None:
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                UPDATE ae_artifacts
                SET updated_at = :updated_at
                WHERE artifact_id = :artifact_id
                """
            ),
            {"artifact_id": artifact_id, "updated_at": updated_at},
        )
        if int(result.rowcount or 0) != 1:
            raise RuntimeError("artifact retention timestamp update failed")


def _db_observations(
    engine: Any,
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    cutoff_at: str,
) -> dict[str, int]:
    params = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
        "cutoff_at": cutoff_at,
    }
    with engine.connect() as connection:
        artifact_rows = _scalar_count(
            connection,
            """
            SELECT count(*)
            FROM ae_artifacts
            WHERE tenant_id = :tenant_id
              AND workspace_id = :workspace_id
              AND owner_user_id = :owner_user_id
            """,
            params,
        )
        deleted_rows = _scalar_count(
            connection,
            """
            SELECT count(*)
            FROM ae_artifacts
            WHERE tenant_id = :tenant_id
              AND workspace_id = :workspace_id
              AND owner_user_id = :owner_user_id
              AND artifact_status = 'DELETED'
            """,
            params,
        )
        candidate_rows = _scalar_count(
            connection,
            """
            SELECT count(*)
            FROM ae_artifacts
            WHERE tenant_id = :tenant_id
              AND workspace_id = :workspace_id
              AND owner_user_id = :owner_user_id
              AND artifact_status = 'DELETED'
              AND updated_at <= :cutoff_at
            """,
            params,
        )
        file_rows = _scalar_count(
            connection,
            """
            SELECT count(*)
            FROM ae_artifact_files
            WHERE artifact_id IN (
                SELECT artifact_id
                FROM ae_artifacts
                WHERE tenant_id = :tenant_id
                  AND workspace_id = :workspace_id
                  AND owner_user_id = :owner_user_id
            )
            """,
            params,
        )
        link_rows = _scalar_count(
            connection,
            """
            SELECT count(*)
            FROM ae_artifact_links
            WHERE artifact_file_id IN (
                SELECT artifact_file_id
                FROM ae_artifact_files
                WHERE artifact_id IN (
                    SELECT artifact_id
                    FROM ae_artifacts
                    WHERE tenant_id = :tenant_id
                      AND workspace_id = :workspace_id
                      AND owner_user_id = :owner_user_id
                )
            )
            """,
            params,
        )
    return {
        "artifact_rows": artifact_rows,
        "deleted_rows": deleted_rows,
        "candidate_rows": candidate_rows,
        "file_rows": file_rows,
        "link_rows": link_rows,
    }


def _candidate_ids(payload: Mapping[str, Any]) -> list[str]:
    return [
        str(item["artifact_id"])
        for item in payload.get("items", [])
        if isinstance(item, Mapping) and item.get("artifact_id")
    ]


def _scalar_count(connection: Any, sql: str, params: dict[str, str]) -> int:
    return int(connection.execute(text(sql), params).scalar() or 0)


def _count_files(root: Path) -> int:
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
    return all(
        fragment not in serialized
        for fragment in forbidden_fragments
        if fragment
    )


def _safe_detail(detail: str, env: Mapping[str, str]) -> str:
    safe = detail
    for key, value in _sensitive_env_values(env):
        replacement = "***" if key.endswith(":password") else f"<redacted:{key}>"
        safe = safe.replace(value, replacement)
    return safe


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    for key, value in _sensitive_env_values(environ):
        if value in serialized_evidence:
            if key.endswith(":password"):
                raise ValueError(
                    "AE artifact retention candidate smoke contains a database "
                    "password."
                )
            raise ValueError(
                f"AE artifact retention candidate smoke contains raw {key}."
            )
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError(
            "AE artifact retention candidate smoke contains a local data path."
        )


def _sensitive_env_values(environ: Mapping[str, str]) -> list[tuple[str, str]]:
    sensitive: list[tuple[str, str]] = []
    for key in (
        service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE),
        "NEX_AE_ARTIFACT_STORAGE_ROOT",
    ):
        value = environ.get(key)
        if value:
            sensitive.append((key, value))
            password = _database_url_password(value)
            if password:
                sensitive.append((f"{key}:password", password))
    return sensitive


def _database_url_password(database_url: str) -> str | None:
    try:
        parsed = urlsplit(database_url)
    except ValueError:
        return None
    if parsed.password is None:
        return None
    return unquote(parsed.password)


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_artifact_retention_candidate_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_retention_candidate_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"candidate_count={evidence['retention']['candidate_count']} "
            f"retention_days={evidence['retention']['retention_days']} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"deleted_artifacts={evidence['cleanup']['artifacts']} "
            f"deleted_handoffs={evidence['cleanup']['handoffs']}"
        )
    return (
        "ae_artifact_retention_candidate_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AE artifact retention candidate PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_artifact_retention_candidate_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
