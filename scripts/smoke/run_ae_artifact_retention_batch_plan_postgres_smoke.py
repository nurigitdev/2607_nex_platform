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


SCHEMA_VERSION = "ae_artifact_retention_batch_plan_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_ARTIFACT_RETENTION_BATCH_PLAN_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_ARTIFACT_RETENTION_BATCH_PLAN_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = artifact_pg.SERVICE_ID
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
AS_OF = "2026-09-01T00:00:00Z"
CHECKED_AT = "2026-09-01T02:30:00Z"
OLD_LOGICAL_PURGE_AT = "2026-07-31T00:00:00Z"
RECENT_LOGICAL_PURGE_AT = "2026-08-30T00:00:00Z"


def run_ae_artifact_retention_batch_plan_postgres_smoke(
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
        execution = _execute_ae_artifact_retention_batch_plan_smoke(
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


def _execute_ae_artifact_retention_batch_plan_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    tenant_id = f"tenant-artifact-retention-plan-{suffix}"
    workspace_id = f"workspace-artifact-retention-plan-{suffix}"
    owner_user_id = f"owner-artifact-retention-plan-{suffix}"
    artifact_ids: list[str] = []
    handoff_ids: list[str] = []
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        with tempfile.TemporaryDirectory(
            prefix="nex-ae-artifact-retention-plan-smoke-",
        ) as storage_dir:
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

                first_old = _create_deleted_artifact(
                    client,
                    headers,
                    engine=engine,
                    suffix=suffix,
                    label="old-first",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    logical_purged_at=OLD_LOGICAL_PURGE_AT,
                )
                second_old = _create_deleted_artifact(
                    client,
                    headers,
                    engine=engine,
                    suffix=suffix,
                    label="old-second",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    logical_purged_at="2026-07-31T01:00:00Z",
                )
                recent = _create_deleted_artifact(
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
                for created in (first_old, second_old, recent):
                    artifact_ids.append(created["artifact_id"])
                    handoff_ids.append(created["artifact_handoff_id"])

                plan_response = client.get(
                    "/api/v1/artifact-retention/batch-plan",
                    params={
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "owner_user_id": owner_user_id,
                        "retention_days": "30",
                        "as_of": AS_OF,
                        "checked_at": CHECKED_AT,
                        "scan_limit": "10",
                        "max_delete_count": "1",
                    },
                    headers={
                        **headers,
                        "Idempotency-Key": f"retention-plan-{suffix}",
                    },
                )
                default_plan_response = client.get(
                    "/api/v1/artifact-retention/batch-plan",
                    params={
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "owner_user_id": owner_user_id,
                        "retention_days": "30",
                        "as_of": AS_OF,
                        "checked_at": "2026-09-01T02:31:00Z",
                        "scan_limit": "10",
                    },
                    headers=headers,
                )
                missing_scope = client.get(
                    "/api/v1/artifact-retention/batch-plan",
                    params={"tenant_id": tenant_id},
                    headers=headers,
                )
                observations = _db_observations(
                    engine,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    cutoff_at="2026-08-02T00:00:00Z",
                )
                materialized_file_count = candidate_pg._count_files(storage_root)
                payload = plan_response.json() if plan_response.status_code == 200 else {}
                default_payload = (
                    default_plan_response.json()
                    if default_plan_response.status_code == 200
                    else {}
                )
                checks = {
                    "plan_route_ok": plan_response.status_code == 200,
                    "plan_schema": payload.get(
                        "artifact_retention_batch_plan_schema_version"
                    )
                    == "ae_artifact_retention_batch_plan.v1",
                    "plan_status_ready": payload.get("plan_status") == "READY",
                    "scheduler_disabled": payload.get("scheduler_status")
                    == "DISABLED",
                    "candidate_count": payload.get("candidate_count") == 2,
                    "selected_count": payload.get("selected_count") == 1,
                    "unselected_count": payload.get("unselected_count") == 1,
                    "selected_oldest": _selected_artifact_ids(payload)
                    == [first_old["artifact_id"]],
                    "estimated_file_deletes": payload.get(
                        "estimated_deleted_counts",
                        {},
                    ).get("files")
                    == 2,
                    "default_delete_limit_selects_all_candidates": (
                        default_plan_response.status_code == 200
                        and default_payload.get("max_delete_count") == 20
                        and default_payload.get("selected_count") == 2
                    ),
                    "missing_scope_rejected": missing_scope.status_code == 422,
                    "db_candidate_rows": observations["candidate_rows"] == 2,
                    "db_deleted_rows_retained": observations["deleted_rows"] == 3,
                    "db_artifact_rows_retained": observations["artifact_rows"] == 3,
                    "db_file_rows_retained": observations["file_rows"] >= 6,
                    "db_link_rows_retained": observations["link_rows"] >= 12,
                    "storage_files_retained": materialized_file_count >= 6,
                    "metadata_only_evidence": _metadata_only(
                        payload,
                        default_payload,
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
                        "AE artifact retention batch plan PostgreSQL smoke checks "
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
                    "batch_plan": {
                        "plan_status": payload["plan_status"],
                        "scheduler_status": payload["scheduler_status"],
                        "candidate_count": payload["candidate_count"],
                        "selected_count": payload["selected_count"],
                        "selected_artifact_ids": _selected_artifact_ids(payload),
                        "default_selected_count": default_payload["selected_count"],
                        "estimated_deleted_counts": payload[
                            "estimated_deleted_counts"
                        ],
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


def _create_deleted_artifact(
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
    return candidate_pg._create_rendered_deleted_artifact(
        client,
        headers,
        engine=engine,
        suffix=suffix,
        label=label,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        logical_purged_at=logical_purged_at,
    )


def _db_observations(
    engine: Any,
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    cutoff_at: str,
) -> dict[str, int]:
    return candidate_pg._db_observations(
        engine,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        cutoff_at=cutoff_at,
    )


def _selected_artifact_ids(payload: Mapping[str, Any]) -> list[str]:
    return [
        str(item["artifact_id"])
        for item in payload.get("selected_candidates", [])
        if isinstance(item, Mapping) and item.get("artifact_id")
    ]


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


def _metadata_only(*payloads: Any, forbidden_fragments: list[str | None]) -> bool:
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
                    "AE artifact retention batch plan smoke contains a database "
                    "password."
                )
            raise ValueError(
                f"AE artifact retention batch plan smoke contains raw {key}."
            )
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError(
            "AE artifact retention batch plan smoke contains a local data path."
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
            "ae_artifact_retention_batch_plan_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_retention_batch_plan_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"candidate_count={evidence['batch_plan']['candidate_count']} "
            f"selected_count={evidence['batch_plan']['selected_count']} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"deleted_artifacts={evidence['cleanup']['artifacts']} "
            f"deleted_handoffs={evidence['cleanup']['handoffs']}"
        )
    return (
        "ae_artifact_retention_batch_plan_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE artifact retention batch plan PostgreSQL smoke."
        )
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_artifact_retention_batch_plan_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
