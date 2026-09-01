#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
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

import run_ae_artifact_postgres_smoke as artifact_pg  # noqa: E402
import run_ae_artifact_retention_candidate_postgres_smoke as candidate_pg  # noqa: E402
import run_ae_artifact_retention_history_postgres_smoke as history_pg  # noqa: E402
import run_ae_oa_auth_postgres_smoke as base_auth  # noqa: E402
from nex_ae_api.artifacts import (  # noqa: E402
    AE_ARTIFACT_RETENTION_EXECUTION_HISTORY_COLLECTION_SCHEMA_VERSION,
    AE_ARTIFACT_RETENTION_EXECUTION_HISTORY_ITEM_SCHEMA_VERSION,
    SqlAlchemyArtifactRetentionExecutionHistoryStore,
    build_artifact_retention_execution,
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


SCHEMA_VERSION = "ae_artifact_retention_history_query_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_ARTIFACT_RETENTION_HISTORY_QUERY_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_ARTIFACT_RETENTION_HISTORY_QUERY_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = artifact_pg.SERVICE_ID
DEFAULT_PROFILE = artifact_pg.DEFAULT_PROFILE
AS_OF = candidate_pg.AS_OF


def run_ae_artifact_retention_history_query_postgres_smoke(
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
            f"{SMOKE_PROFILE_ENV} must be test for query smoke execution.",
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
        execution = _execute_ae_artifact_retention_history_query_smoke(
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


def _execute_ae_artifact_retention_history_query_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    tenant_id = f"tenant-artifact-history-query-{suffix}"
    workspace_id = f"workspace-artifact-history-query-{suffix}"
    owner_user_id = f"owner-artifact-history-query-{suffix}"
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        store = SqlAlchemyArtifactRetentionExecutionHistoryStore(session_factory)
        seeded = _seed_history_records(
            store,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            request_id=request_id,
            trace_id=trace_id,
            suffix=suffix,
        )
        app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        app.state.nex_persistence = SimpleNamespace(
            api_session_factory=session_factory
        )
        register_artifact_handoff_routes(app)
        client = TestClient(app)
        headers = artifact_pg._auth_headers(
            request_id=request_id,
            trace_id=trace_id,
        )
        all_history = _get_history(
            client,
            headers=headers,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            limit="10",
        )
        execute_history = _get_history(
            client,
            headers=headers,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            mode="execute",
            limit="10",
        )
        blocked_history = _get_history(
            client,
            headers=headers,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            execution_status="blocked",
            limit="1",
        )
        invalid_mode = _get_history(
            client,
            headers=headers,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            mode="preview",
        )
        unauthorized = _get_history(
            client,
            headers={},
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        )
        db_after = history_pg._history_observations(
            engine,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        )
        db_rows = history_pg._history_rows(
            engine,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        )
        all_body = all_history["body"]
        execute_body = execute_history["body"]
        blocked_body = blocked_history["body"]
        checks = _checks(
            all_history=all_history,
            execute_history=execute_history,
            blocked_history=blocked_history,
            invalid_mode=invalid_mode,
            unauthorized=unauthorized,
            db_after=db_after,
            db_rows=db_rows,
            seeded=seeded,
            database_url=database_url,
            database_env=database_env,
        )
        failed_checks = [key for key, passed in checks.items() if not passed]
        if failed_checks:
            raise RuntimeError(
                "AE artifact retention history query PostgreSQL smoke checks "
                f"failed: {', '.join(failed_checks)}"
            )
        cleanup_history = history_pg._cleanup_history_rows(
            engine,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        )
        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "history_scope": {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
            },
            "seeded_execution_ids": [
                record["retention_execution_id"] for record in seeded
            ],
            "route_results": {
                "all": _route_summary(all_body),
                "execute": _route_summary(execute_body),
                "blocked": _route_summary(blocked_body),
                "invalid_mode_status_code": invalid_mode["status_code"],
                "unauthorized_status_code": unauthorized["status_code"],
            },
            "db_after": db_after,
            "db_row_summaries": _db_row_summaries(db_rows),
            "checks": checks,
            "cleanup": {"history_rows": cleanup_history},
            "live_db": True,
        }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        history_pg._cleanup_history_rows(
            engine,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
        )
        engine.dispose()


def _seed_history_records(
    store: SqlAlchemyArtifactRetentionExecutionHistoryStore,
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    request_id: str,
    trace_id: str,
    suffix: str,
) -> list[dict[str, Any]]:
    executions = [
        build_artifact_retention_execution(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            execution_status="SUCCEEDED",
            as_of=AS_OF,
            checked_at="2026-09-01T02:40:00Z",
            candidate_count=2,
            selected_count=1,
            idempotency_key=f"history-query-dry-{suffix}",
            request_id=request_id,
            trace_id=trace_id,
        ),
        build_artifact_retention_execution(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            mode="EXECUTE",
            execution_status="BLOCKED",
            as_of=AS_OF,
            checked_at="2026-09-01T02:45:00Z",
            candidate_count=2,
            selected_count=0,
            blocked_reason="delete_not_enabled",
            idempotency_key=f"history-query-blocked-{suffix}",
            request_id=request_id,
            trace_id=trace_id,
        ),
        build_artifact_retention_execution(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            mode="EXECUTE",
            execution_status="SUCCEEDED",
            as_of=AS_OF,
            checked_at="2026-09-01T02:50:00Z",
            candidate_count=2,
            selected_count=1,
            deleted_counts={
                "artifacts": 1,
                "source_refs": 1,
                "versions": 1,
                "render_jobs": 1,
                "files": 2,
                "links": 4,
                "storage_files": 2,
            },
            delete_enabled=True,
            storage_mutation_enabled=True,
            database_row_delete_enabled=True,
            idempotency_key=f"history-query-execute-{suffix}",
            request_id=request_id,
            trace_id=trace_id,
        ),
    ]
    return [store.save(execution) for execution in executions]


def _get_history(
    client: TestClient,
    *,
    headers: Mapping[str, str],
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    mode: str | None = None,
    execution_status: str | None = None,
    limit: str | None = None,
) -> dict[str, Any]:
    params = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
        **({"mode": mode} if mode is not None else {}),
        **({"execution_status": execution_status} if execution_status is not None else {}),
        **({"limit": limit} if limit is not None else {}),
    }
    response = client.get(
        "/api/v1/artifact-retention/executions",
        params=params,
        headers=dict(headers),
    )
    return {"status_code": response.status_code, "body": _safe_response_json(response)}


def _checks(
    *,
    all_history: dict[str, Any],
    execute_history: dict[str, Any],
    blocked_history: dict[str, Any],
    invalid_mode: dict[str, Any],
    unauthorized: dict[str, Any],
    db_after: dict[str, int],
    db_rows: list[dict[str, Any]],
    seeded: list[dict[str, Any]],
    database_url: str,
    database_env: str,
) -> dict[str, bool]:
    all_body = all_history["body"]
    execute_body = execute_history["body"]
    blocked_body = blocked_history["body"]
    all_items = _items(all_body)
    execute_items = _items(execute_body)
    blocked_items = _items(blocked_body)
    expected_order = [
        seeded[2]["retention_execution_id"],
        seeded[1]["retention_execution_id"],
        seeded[0]["retention_execution_id"],
    ]
    return {
        "seed_rows_written": len(seeded) == 3,
        "db_rows_written": db_after["history_rows"] == 3,
        "db_execute_rows_written": db_after["execute_rows"] == 2,
        "route_all_ok": all_history["status_code"] == 200,
        "route_collection_schema": all_body.get(
            "artifact_retention_execution_history_collection_schema_version"
        )
        == AE_ARTIFACT_RETENTION_EXECUTION_HISTORY_COLLECTION_SCHEMA_VERSION,
        "route_all_count_matches_db": all_body.get("count") == db_after["history_rows"],
        "route_all_items_ordered_desc": [
            item.get("retention_execution_id") for item in all_items
        ]
        == expected_order,
        "route_items_are_metadata_only": all(
            item.get("artifact_retention_execution_history_item_schema_version")
            == AE_ARTIFACT_RETENTION_EXECUTION_HISTORY_ITEM_SCHEMA_VERSION
            and "execution" not in item
            for item in all_items
        ),
        "route_execute_filter_ok": execute_history["status_code"] == 200
        and execute_body.get("count") == 2
        and all(item.get("mode") == "EXECUTE" for item in execute_items),
        "route_blocked_filter_ok": blocked_history["status_code"] == 200
        and blocked_body.get("count") == 1
        and bool(blocked_items)
        and blocked_items[0].get("execution_status") == "BLOCKED",
        "route_summary_matches_db": all_body.get("summary", {}).get("execute_count")
        == db_after["execute_rows"]
        and all_body.get("summary", {}).get("blocked_count")
        == db_after["blocked_rows"],
        "route_invalid_mode_rejected": invalid_mode["status_code"] == 422,
        "route_unauthorized_rejected": unauthorized["status_code"] == 401,
        "history_hashes_present": all(
            len(row["execution_payload_hash"]) == 64 for row in db_rows
        ),
        "history_payloads_match_flat_columns": all(
            row["execution"]["execution_id"] == row["retention_execution_id"]
            and row["execution"]["mode"] == row["mode"]
            and row["execution"]["execution_status"] == row["execution_status"]
            for row in db_rows
        ),
        "metadata_only_evidence": _metadata_only(
            all_history,
            execute_history,
            blocked_history,
            db_after,
            _db_row_summaries(db_rows),
            forbidden_fragments=[
                database_url,
                database_env,
                _database_url_password(database_url),
                "/data/nex-platform",
                "storage_ref",
                "content_base64",
                "rendered_payloads",
                '"execution":',
            ],
        ),
    }


def _db_row_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "retention_execution_id": row["retention_execution_id"],
            "mode": row["mode"],
            "execution_status": row["execution_status"],
            "idempotency_key": row["idempotency_key"],
            "deleted_artifacts": row["deleted_counts"].get("artifacts", 0),
            "execution_payload_hash_present": (
                len(row["execution_payload_hash"]) == 64
            ),
            "execution_payload_matches_columns": (
                row["execution"]["execution_id"] == row["retention_execution_id"]
                and row["execution"]["mode"] == row["mode"]
                and row["execution"]["execution_status"] == row["execution_status"]
            ),
            "checked_at": row["checked_at"],
        }
        for row in rows
    ]


def _route_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": payload.get(
            "artifact_retention_execution_history_collection_schema_version"
        ),
        "count": payload.get("count"),
        "summary": payload.get("summary", {}),
        "item_ids": [
            item.get("retention_execution_id")
            for item in _items(payload)
        ],
    }


def _items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, Mapping)]


def _safe_response_json(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _metadata_only(
    *payloads: Any,
    forbidden_fragments: list[str | None],
) -> bool:
    serialized = json.dumps(payloads, ensure_ascii=False, default=str)
    return not any(fragment and fragment in serialized for fragment in forbidden_fragments)


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
                    "AE artifact retention history query smoke contains a database password."
                )
            raise ValueError(
                f"AE artifact retention history query smoke contains raw {key}."
            )
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError(
            "AE artifact retention history query smoke contains a local data path."
        )
    if '"execution":' in serialized_evidence:
        raise ValueError(
            "AE artifact retention history query smoke contains raw execution JSON."
        )


def _sensitive_env_values(environ: Mapping[str, str]) -> list[tuple[str, str]]:
    database_env = service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE)
    value = environ.get(database_env)
    if not value:
        return []
    sensitive = [(database_env, value)]
    password = _database_url_password(value)
    if password:
        sensitive.append((f"{database_env}:password", password))
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
            "ae_artifact_retention_history_query_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_retention_history_query_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"route_count={evidence['route_results']['all']['count']} "
            f"db_history_rows={evidence['db_after']['history_rows']} "
            f"blocked={evidence['route_results']['blocked']['count']} "
            f"live_db={str(evidence['live_db']).lower()} "
            f"cleanup_history={evidence['cleanup']['history_rows']}"
        )
    return (
        "ae_artifact_retention_history_query_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AE artifact retention history query PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_artifact_retention_history_query_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
