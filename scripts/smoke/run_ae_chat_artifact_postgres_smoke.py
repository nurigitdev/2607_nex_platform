#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
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
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AE_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))

from nex_ae_api.chat import register_chat_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SCHEMA_VERSION = "ae_chat_artifact_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_CHAT_ARTIFACT_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_CHAT_ARTIFACT_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = "nex-ae-api"
DEFAULT_PROFILE = "test"
MIGRATION_VERSION = "0407_ae_chat_artifact_refs_foundation"
EXPECTED_TABLES = {"ae_chat_interactions", "ae_chat_artifact_refs"}
EXPECTED_INDEXES = {
    "idx_ae_chat_interactions_user",
    "idx_ae_chat_artifact_refs_owner_time",
    "idx_ae_chat_artifact_refs_chat_time",
    "idx_ae_chat_artifact_refs_artifact",
    "idx_ae_chat_artifact_refs_generation",
}
EXPECTED_JSONB_TYPES = {
    "retrieval_summary": "jsonb",
    "generation_summary": "jsonb",
    "failure_summary": "jsonb",
    "available_formats": "jsonb",
    "download_routes": "jsonb",
    "quality_summary": "jsonb",
    "actions": "jsonb",
}


class FakeCxGenerationClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "payload": payload,
                "request_id": request_id,
                "trace_id": trace_id,
            }
        )
        return {
            "cx_generation_id": payload.get("cx_generation_id") or "cx-gen-smoke",
            "status": "COMPLETED",
            "alias": payload["alias"],
            "provider_capability": payload["provider_capability"],
            "mo_generation_id": "mo-gen-smoke",
            "request_metadata": {
                "grounding_required": False,
                "structured_draft_id": None,
            },
            "response_metadata": {
                "finish_reason": "STOP",
                "output_preview": "Artifact-ready answer.",
            },
            "usage": {"input_tokens": 7, "output_tokens": 11, "total_tokens": 18},
        }


def run_ae_chat_artifact_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    if profile != "test":
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
            env=env,
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_chat_artifact_smoke(
            database_url=database_url,
            database_env=database_env,
        )
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile, env=env)
    except Exception as exc:
        return _failure(
            "execution_failed",
            str(exc) or exc.__class__.__name__,
            profile=profile,
            env=env,
        )

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


def _execute_chat_artifact_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    interaction_id = str(uuid4())
    chat_document_id = str(uuid4())
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        app.state.nex_persistence = SimpleNamespace(api_session_factory=session_factory)
        cx_client = FakeCxGenerationClient()
        register_chat_routes(app, cx_client=cx_client)
        client = TestClient(app)
        headers = _auth_headers(request_id=request_id, trace_id=trace_id)

        create_response = client.post(
            "/api/v1/chat/interactions",
            json={
                "interaction_id": interaction_id,
                "chat_document_id": chat_document_id,
                "tenant_id": f"tenant-chat-artifact-smoke-{suffix}",
                "user_id": f"user-chat-artifact-smoke-{suffix}",
                "user_message": "Create a short artifact from the selected result.",
                "generation": {
                    "alias": "general-llm-default",
                    "provider_capability": "generation",
                },
            },
            headers=headers,
        )
        if create_response.status_code != 200:
            raise RuntimeError("AE chat interaction create route failed")
        chat_record = create_response.json()

        artifact_record = _artifact_record(
            suffix=suffix,
            interaction_id=interaction_id,
            chat_document_id=chat_document_id,
        )
        attach_response = client.post(
            f"/api/v1/chat/interactions/{interaction_id}/artifact-links",
            json={"artifact": artifact_record},
            headers=headers,
        )
        if attach_response.status_code != 200:
            raise RuntimeError("AE chat artifact link attach route failed")
        repeat_response = client.post(
            f"/api/v1/chat/interactions/{interaction_id}/artifact-links",
            json={"artifact": artifact_record},
            headers=headers,
        )
        read_response = client.get(
            f"/api/v1/chat/interactions/{interaction_id}",
            headers=headers,
        )
        list_response = client.get(
            f"/api/v1/chat/interactions/{interaction_id}/artifact-links",
            headers=headers,
        )
        attached = attach_response.json()
        listed = list_response.json()
        observations = _db_observations(engine, interaction_id=interaction_id)
        cleanup = _cleanup_chat_rows(engine, interaction_id=interaction_id)

        checks = {
            "chat_created": create_response.status_code == 200
            and chat_record["interaction_id"] == interaction_id,
            "artifact_link_attached": attach_response.status_code == 200
            and len(attached["artifact_refs"]) == 1,
            "artifact_link_idempotent": repeat_response.status_code == 200
            and len(repeat_response.json()["artifact_refs"]) == 1,
            "chat_readback": read_response.status_code == 200
            and read_response.json()["artifact_refs"] == attached["artifact_refs"],
            "artifact_links_listed": list_response.status_code == 200
            and listed["artifact_refs"] == attached["artifact_refs"],
            "table_family_present": observations["tables_present"]
            == sorted(EXPECTED_TABLES),
            "migration_recorded": observations["migration_recorded"] is True,
            "row_counts": observations["row_counts"]
            == {"interactions": 1, "artifact_refs": 1},
            "jsonb_columns": observations["jsonb_columns"] == EXPECTED_JSONB_TYPES,
            "indexes_present": observations["indexes_present"]
            == sorted(EXPECTED_INDEXES),
            "owner_scope_persisted": observations["owner_scope"]
            == {
                "tenant_id": f"tenant-chat-artifact-smoke-{suffix}",
                "user_id": f"user-chat-artifact-smoke-{suffix}",
            },
            "cleanup_deleted": cleanup == {"interactions": 1, "artifact_refs": 1},
            "raw_sensitive_absent": _redaction_safe(
                chat_record,
                attached,
                listed,
                observations,
                forbidden_fragments=[
                    database_url,
                    database_env,
                    "nuri1004",
                    "/data/nex-platform",
                    "hidden prompt",
                    "raw source",
                ],
            ),
        }
        failed_checks = [key for key, passed in checks.items() if not passed]
        if failed_checks:
            raise RuntimeError(
                "AE chat artifact PostgreSQL smoke checks failed: "
                f"{', '.join(failed_checks)}"
            )
        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "interaction_id": interaction_id,
            "chat_document_id": chat_document_id,
            "artifact_id": artifact_record["artifact_id"],
            "artifact_version_id": artifact_record["current_version_id"],
            "cx_client_call_count": len(cx_client.calls),
            "db_observations": observations,
            "checks": checks,
            "cleanup": cleanup,
        }
    except (SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        _cleanup_chat_rows(engine, interaction_id=interaction_id)
        engine.dispose()


def _artifact_record(
    *,
    suffix: str,
    interaction_id: str,
    chat_document_id: str,
) -> dict[str, Any]:
    artifact_file_id = f"artifact-file-chat-smoke-{suffix}"
    artifact_version_id = f"artifact-version-chat-smoke-{suffix}"
    return {
        "artifact_id": f"artifact-chat-smoke-{suffix}",
        "artifact_type": "generated_document",
        "artifact_status": "READY",
        "current_version_id": artifact_version_id,
        "chat_document_id": chat_document_id,
        "interaction_id": interaction_id,
        "display_title": "Artifact chat smoke",
        "target_formats": ["MD", "HTML_PREVIEW"],
        "source_refs": [
            {
                "cx_generation_id": f"cx-gen-chat-smoke-{suffix}",
                "structured_draft_content_hash": "c" * 64,
                "quality_summary": {
                    "citation_status": "VALIDATED",
                    "citation_count": 1,
                    "validation_error_count": 0,
                    "warning_count": 0,
                    "grounding_required": True,
                    "retrieval_package_id": f"retrieval-chat-smoke-{suffix}",
                    "retrieval_package_hash": "d" * 64,
                    "evidence_ref_count": 1,
                },
            }
        ],
        "versions": [
            {
                "artifact_version_id": artifact_version_id,
                "source_content_hash": "c" * 64,
            }
        ],
        "files": [{"artifact_file_id": artifact_file_id, "format": "MD"}],
        "links": [
            {
                "artifact_file_id": artifact_file_id,
                "link_type": "preview",
                "link_route": f"/api/v1/artifact-files/{artifact_file_id}/preview",
            },
            {
                "artifact_file_id": artifact_file_id,
                "link_type": "download",
                "link_route": f"/api/v1/artifact-files/{artifact_file_id}/download",
            },
        ],
    }


def _auth_headers(*, request_id: str, trace_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ag", audience=SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _db_observations(engine: Any, *, interaction_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        tables_present = sorted(
            table_name
            for table_name in EXPECTED_TABLES
            if connection.execute(
                text(f"SELECT to_regclass('public.{table_name}')")
            ).scalar()
            == table_name
        )
        migration_recorded = connection.execute(
            text(
                """
                SELECT EXISTS(
                    SELECT 1 FROM schema_migrations WHERE version = :version
                )
                """
            ),
            {"version": MIGRATION_VERSION},
        ).scalar()
        row_counts = {
            "interactions": _scalar_count(
                connection,
                """
                SELECT count(*) FROM ae_chat_interactions
                WHERE chat_interaction_id = :interaction_id
                """,
                {"interaction_id": interaction_id},
            ),
            "artifact_refs": _scalar_count(
                connection,
                """
                SELECT count(*) FROM ae_chat_artifact_refs
                WHERE chat_interaction_id = :interaction_id
                """,
                {"interaction_id": interaction_id},
            ),
        }
        jsonb_row = (
            connection.execute(
                text(
                    """
                    SELECT
                        pg_typeof(i.retrieval_summary)::text AS retrieval_summary,
                        pg_typeof(i.generation_summary)::text AS generation_summary,
                        pg_typeof(i.failure_summary)::text AS failure_summary,
                        pg_typeof(r.available_formats)::text AS available_formats,
                        pg_typeof(r.download_routes)::text AS download_routes,
                        pg_typeof(r.quality_summary)::text AS quality_summary,
                        pg_typeof(r.actions)::text AS actions
                    FROM ae_chat_interactions i
                    JOIN ae_chat_artifact_refs r
                      ON r.chat_interaction_id = i.chat_interaction_id
                    WHERE i.chat_interaction_id = :interaction_id
                    LIMIT 1
                    """
                ),
                {"interaction_id": interaction_id},
            )
            .mappings()
            .first()
        )
        indexes = (
            connection.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename IN (
                        'ae_chat_interactions',
                        'ae_chat_artifact_refs'
                      )
                    ORDER BY indexname
                    """
                )
            )
            .scalars()
            .all()
        )
        owner_scope = (
            connection.execute(
                text(
                    """
                    SELECT tenant_id, user_id
                    FROM ae_chat_interactions
                    WHERE chat_interaction_id = :interaction_id
                    """
                ),
                {"interaction_id": interaction_id},
            )
            .mappings()
            .first()
        )
    return {
        "tables_present": tables_present,
        "migration_recorded": bool(migration_recorded),
        "row_counts": row_counts,
        "jsonb_columns": dict(jsonb_row) if jsonb_row else {},
        "indexes_present": sorted(set(indexes).intersection(EXPECTED_INDEXES)),
        "owner_scope": dict(owner_scope) if owner_scope else {},
    }


def _scalar_count(connection: Any, sql: str, params: dict[str, str]) -> int:
    return int(connection.execute(text(sql), params).scalar() or 0)


def _cleanup_chat_rows(engine: Any, *, interaction_id: str | None) -> dict[str, int]:
    deleted = {"interactions": 0, "artifact_refs": 0}
    if interaction_id is None:
        return deleted
    try:
        with engine.begin() as connection:
            ref_result = connection.execute(
                text(
                    """
                    DELETE FROM ae_chat_artifact_refs
                    WHERE chat_interaction_id = :interaction_id
                    """
                ),
                {"interaction_id": interaction_id},
            )
            interaction_result = connection.execute(
                text(
                    """
                    DELETE FROM ae_chat_interactions
                    WHERE chat_interaction_id = :interaction_id
                    """
                ),
                {"interaction_id": interaction_id},
            )
            deleted["artifact_refs"] = int(ref_result.rowcount or 0)
            deleted["interactions"] = int(interaction_result.rowcount or 0)
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


def _redaction_safe(
    *payloads: Any,
    forbidden_fragments: list[str],
) -> bool:
    serialized = json.dumps(payloads, ensure_ascii=False, sort_keys=True, default=str)
    return all(fragment not in serialized for fragment in forbidden_fragments)


def _safe_detail(detail: str, env: Mapping[str, str]) -> str:
    safe = detail
    database_env = service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE)
    database_url = env.get(database_env)
    if database_url:
        safe = safe.replace(database_url, f"<redacted:{database_env}>")
    return safe.replace("nuri1004", "***")


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    database_env = service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE)
    database_url = environ.get(database_env)
    if database_url and database_url in serialized_evidence:
        raise ValueError("AE chat artifact smoke contains raw database URL.")
    if "nuri1004" in serialized_evidence:
        raise ValueError("AE chat artifact smoke contains a database password.")
    if "/data/nex-platform" in serialized_evidence:
        raise ValueError("AE chat artifact smoke contains a local data path.")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ae_chat_artifact_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "ae_chat_artifact_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"interaction_id={evidence['interaction_id']} "
            f"artifact_id={evidence['artifact_id']} "
            f"rows={sum(evidence['db_observations']['row_counts'].values())} "
            f"deleted_interactions={evidence['cleanup']['interactions']} "
            f"deleted_artifact_refs={evidence['cleanup']['artifact_refs']}"
        )
    return (
        "ae_chat_artifact_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AE chat artifact PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_chat_artifact_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
