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
import run_ae_artifact_retention_candidate_postgres_smoke as candidate_pg  # noqa: E402
import run_ae_artifact_retention_purge_postgres_smoke as purge_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifacts import (  # noqa: E402
    build_artifact_retention_operator_approval,
    register_artifact_handoff_routes,
)
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


SCHEMA_VERSION = "ae_artifact_retention_history_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_ARTIFACT_RETENTION_HISTORY_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_ARTIFACT_RETENTION_HISTORY_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = artifact_pg.SERVICE_ID
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
AS_OF = candidate_pg.AS_OF
OLD_LOGICAL_PURGE_AT = candidate_pg.OLD_LOGICAL_PURGE_AT
RECENT_LOGICAL_PURGE_AT = candidate_pg.RECENT_LOGICAL_PURGE_AT
CUTOFF_AT = purge_pg.CUTOFF_AT


def run_ae_artifact_retention_history_postgres_smoke(
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
        execution = _execute_ae_artifact_retention_history_smoke(
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


def _execute_ae_artifact_retention_history_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    tenant_id = f"tenant-artifact-history-{suffix}"
    workspace_id = f"workspace-artifact-history-{suffix}"
    owner_user_id = f"owner-artifact-history-{suffix}"
    artifact_ids: list[str] = []
    handoff_ids: list[str] = []
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        with tempfile.TemporaryDirectory(prefix="nex-ae-artifact-history-smoke-") as storage_dir:
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

                old_deleted = candidate_pg._create_rendered_deleted_artifact(
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
                recent_deleted = candidate_pg._create_rendered_deleted_artifact(
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

                before = purge_pg._db_observations(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    cutoff_at=CUTOFF_AT,
                )
                history_before = _history_observations(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                )
                materialized_before = candidate_pg._count_files(storage_root)
                purge_payload = {
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "owner_user_id": owner_user_id,
                    "retention_days": "30",
                    "as_of": AS_OF,
                    "scan_limit": "10",
                    "max_delete_count": "1",
                    "requested_by": {
                        "actor_type": "service",
                        "actor_id": "nex-ag",
                    },
                }
                dry_run = purge_pg._post_purge(
                    client,
                    headers,
                    payload={**purge_payload, "checked_at": "2026-09-01T02:50:00Z"},
                    idempotency_key=f"retention-history-dry-{suffix}",
                )
                duplicate_dry_run = purge_pg._post_purge(
                    client,
                    headers,
                    payload={**purge_payload, "checked_at": "2026-09-01T02:51:00Z"},
                    idempotency_key=f"retention-history-dry-{suffix}",
                )
                blocked = purge_pg._post_purge(
                    client,
                    headers,
                    payload={
                        **purge_payload,
                        "checked_at": "2026-09-01T02:55:00Z",
                        "dry_run": False,
                    },
                    idempotency_key=f"retention-history-blocked-{suffix}",
                )
                execute = purge_pg._post_purge(
                    client,
                    headers,
                    payload={
                        **purge_payload,
                        "checked_at": "2026-09-01T03:00:00Z",
                        "dry_run": False,
                        "delete_enabled": True,
                        "storage_mutation_enabled": True,
                        "database_row_delete_enabled": True,
                        "operator_approval": build_artifact_retention_operator_approval(
                            tenant_id=tenant_id,
                            workspace_id=workspace_id,
                            owner_user_id=owner_user_id,
                            operator_id="history-smoke-operator",
                            approved_at="2026-09-01T02:59:00Z",
                            approval_reason=(
                                "Verified history smoke dry-run before execute."
                            ),
                            approval_ticket=f"AE-RET-HISTORY-{suffix}",
                        ),
                    },
                    idempotency_key=f"retention-history-execute-{suffix}",
                )
                duplicate_execute = purge_pg._post_purge(
                    client,
                    headers,
                    payload={
                        **purge_payload,
                        "checked_at": "2026-09-01T03:01:00Z",
                        "dry_run": False,
                        "delete_enabled": True,
                        "storage_mutation_enabled": True,
                        "database_row_delete_enabled": True,
                        "operator_approval": build_artifact_retention_operator_approval(
                            tenant_id=tenant_id,
                            workspace_id=workspace_id,
                            owner_user_id=owner_user_id,
                            operator_id="history-smoke-operator",
                            approved_at="2026-09-01T02:59:00Z",
                            approval_reason=(
                                "Verified history smoke dry-run before execute."
                            ),
                            approval_ticket=f"AE-RET-HISTORY-{suffix}",
                        ),
                    },
                    idempotency_key=f"retention-history-execute-{suffix}",
                )
                after_execute = purge_pg._db_observations(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    cutoff_at=CUTOFF_AT,
                )
                history_after = _history_observations(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                )
                history_rows = _history_rows(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                )
                materialized_after = candidate_pg._count_files(storage_root)
                execute_body = execute["body"]
                duplicate_execute_body = duplicate_execute["body"]
                checks = {
                    "initial_candidate_rows": before["candidate_rows"] == 1,
                    "initial_history_empty": history_before["history_rows"] == 0,
                    "initial_storage_files": materialized_before >= 4,
                    "dry_run_route_ok": dry_run["status_code"] == 200,
                    "dry_run_succeeded": dry_run["body"].get("mode") == "DRY_RUN"
                    and dry_run["body"].get("execution_status") == "SUCCEEDED",
                    "dry_run_idempotency_reused": duplicate_dry_run["status_code"] == 200
                    and duplicate_dry_run["body"].get("execution_id")
                    == dry_run["body"].get("execution_id")
                    and duplicate_dry_run["body"].get("checked_at")
                    == dry_run["body"].get("checked_at"),
                    "blocked_route_ok": blocked["status_code"] == 200,
                    "blocked_history_saved": blocked["body"].get("execution_status")
                    == "BLOCKED",
                    "execute_route_ok": execute["status_code"] == 200,
                    "execute_succeeded": execute_body.get("execution_status")
                    == "SUCCEEDED",
                    "execute_deleted_one_artifact": execute_body.get(
                        "deleted_counts",
                        {},
                    ).get("artifacts")
                    == 1,
                    "execute_idempotency_reused": duplicate_execute["status_code"] == 200
                    and duplicate_execute_body.get("execution_id")
                    == execute_body.get("execution_id")
                    and duplicate_execute_body.get("deleted_counts", {}).get("artifacts")
                    == 1,
                    "history_rows_written": history_after["history_rows"] == 3,
                    "history_modes_written": history_after["dry_run_rows"] == 1
                    and history_after["execute_rows"] == 2,
                    "history_statuses_written": history_after["succeeded_rows"] == 2
                    and history_after["blocked_rows"] == 1,
                    "history_hashes_present": all(
                        len(row["execution_payload_hash"]) == 64 for row in history_rows
                    ),
                    "history_payloads_match_flat_columns": all(
                        row["execution"]["execution_id"]
                        == row["retention_execution_id"]
                        and row["execution"]["mode"] == row["mode"]
                        and row["execution"]["execution_status"]
                        == row["execution_status"]
                        for row in history_rows
                    ),
                    "history_deleted_counts_persisted": any(
                        row["mode"] == "EXECUTE"
                        and row["execution_status"] == "SUCCEEDED"
                        and row["deleted_counts"].get("artifacts") == 1
                        for row in history_rows
                    ),
                    "db_old_artifact_deleted": after_execute["artifact_rows"] == 1,
                    "db_candidate_rows_zero": after_execute["candidate_rows"] == 0,
                    "db_handoff_rows_retained": after_execute["handoff_rows"] == 2,
                    "storage_files_removed": materialized_after == 2,
                    "metadata_only_evidence": candidate_pg._metadata_only(
                        dry_run,
                        duplicate_dry_run,
                        blocked,
                        execute,
                        duplicate_execute,
                        history_after,
                        history_rows,
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
                        "AE artifact retention history PostgreSQL smoke checks "
                        f"failed: {', '.join(failed_checks)}"
                    )
                cleanup_history = _cleanup_history_rows(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
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
                        "cutoff_at": execute_body["cutoff_at"],
                        "dry_run_execution_id": dry_run["body"]["execution_id"],
                        "blocked_execution_id": blocked["body"]["execution_id"],
                        "execute_execution_id": execute_body["execution_id"],
                        "execute_duplicate_execution_id": duplicate_execute_body[
                            "execution_id"
                        ],
                        "deleted_counts": execute_body["deleted_counts"],
                    },
                    "db_before": before,
                    "db_after_execute": after_execute,
                    "history_before": history_before,
                    "history_after": history_after,
                    "history_rows": history_rows,
                    "materialized_file_count": {
                        "before": materialized_before,
                        "after_execute": materialized_after,
                    },
                    "checks": checks,
                    "cleanup": {**cleanup, "history_rows": cleanup_history},
                    "live_db": True,
                }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        _cleanup_history_rows(
            engine,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        )
        collection_pg._cleanup_smoke_rows(
            engine,
            artifact_ids=artifact_ids,
            artifact_handoff_ids=handoff_ids,
        )
        engine.dispose()


def _history_observations(
    engine: Any,
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
) -> dict[str, int]:
    params = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
    }
    with engine.connect() as connection:
        return {
            "history_rows": candidate_pg._scalar_count(
                connection,
                """
                SELECT count(*)
                FROM ae_artifact_retention_executions
                WHERE tenant_id = :tenant_id
                  AND workspace_id = :workspace_id
                  AND owner_user_id = :owner_user_id
                """,
                params,
            ),
            "dry_run_rows": candidate_pg._scalar_count(
                connection,
                """
                SELECT count(*)
                FROM ae_artifact_retention_executions
                WHERE tenant_id = :tenant_id
                  AND workspace_id = :workspace_id
                  AND owner_user_id = :owner_user_id
                  AND mode = 'DRY_RUN'
                """,
                params,
            ),
            "execute_rows": candidate_pg._scalar_count(
                connection,
                """
                SELECT count(*)
                FROM ae_artifact_retention_executions
                WHERE tenant_id = :tenant_id
                  AND workspace_id = :workspace_id
                  AND owner_user_id = :owner_user_id
                  AND mode = 'EXECUTE'
                """,
                params,
            ),
            "succeeded_rows": candidate_pg._scalar_count(
                connection,
                """
                SELECT count(*)
                FROM ae_artifact_retention_executions
                WHERE tenant_id = :tenant_id
                  AND workspace_id = :workspace_id
                  AND owner_user_id = :owner_user_id
                  AND execution_status = 'SUCCEEDED'
                """,
                params,
            ),
            "blocked_rows": candidate_pg._scalar_count(
                connection,
                """
                SELECT count(*)
                FROM ae_artifact_retention_executions
                WHERE tenant_id = :tenant_id
                  AND workspace_id = :workspace_id
                  AND owner_user_id = :owner_user_id
                  AND execution_status = 'BLOCKED'
                """,
                params,
            ),
        }


def _history_rows(
    engine: Any,
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    """
                    SELECT
                        retention_execution_id,
                        mode,
                        execution_status,
                        idempotency_key,
                        deleted_counts,
                        execution,
                        execution_payload_hash,
                        checked_at
                    FROM ae_artifact_retention_executions
                    WHERE tenant_id = :tenant_id
                      AND workspace_id = :workspace_id
                      AND owner_user_id = :owner_user_id
                    ORDER BY checked_at ASC, retention_execution_id ASC
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "owner_user_id": owner_user_id,
                },
            )
            .mappings()
            .all()
        )
    return [
        {
            "retention_execution_id": row["retention_execution_id"],
            "mode": row["mode"],
            "execution_status": row["execution_status"],
            "idempotency_key": row["idempotency_key"],
            "deleted_counts": _json_value(row["deleted_counts"], {}),
            "execution": _json_value(row["execution"], {}),
            "execution_payload_hash": row["execution_payload_hash"],
            "checked_at": _datetime_value(row["checked_at"]),
        }
        for row in rows
    ]


def _cleanup_history_rows(
    engine: Any,
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
) -> int:
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    DELETE FROM ae_artifact_retention_executions
                    WHERE tenant_id = :tenant_id
                      AND workspace_id = :workspace_id
                      AND owner_user_id = :owner_user_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "owner_user_id": owner_user_id,
                },
            )
            return int(result.rowcount or 0)
    except SQLAlchemyError:
        return 0


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def _datetime_value(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


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
                    "AE artifact retention history smoke contains a database password."
                )
            raise ValueError(
                f"AE artifact retention history smoke contains raw {key}."
            )
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError(
            "AE artifact retention history smoke contains a local data path."
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


def _database_url_password(database_url: str | None) -> str | None:
    if database_url is None:
        return None
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
            "ae_artifact_retention_history_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_retention_history_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"history_rows={evidence['history_after']['history_rows']} "
            f"deleted_artifacts={evidence['retention']['deleted_counts']['artifacts']} "
            f"idempotency_reused="
            f"{str(evidence['checks']['execute_idempotency_reused']).lower()} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"cleanup_history={evidence['cleanup']['history_rows']}"
        )
    return (
        "ae_artifact_retention_history_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AE artifact retention history PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_artifact_retention_history_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
