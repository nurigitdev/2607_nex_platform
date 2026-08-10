#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
CX_PATH = ROOT / "services" / "nex-cx"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(CX_PATH))

from nex_cx.ingestion import (  # noqa: E402
    ContentIngestionStore,
    CxStorageConfig,
    UPLOAD_OWNER_RESOLVER_VERIFY,
    register_ingestion_routes,
)
from nex_cx.repository import SqlAlchemyCxContentRepository  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_engine,
    build_service_app,
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


SMOKE_ENV = "NEX_CX_UPLOAD_OWNERSHIP_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_CX_UPLOAD_OWNERSHIP_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SERVICE_SPEC = SERVICE_SPECS[SERVICE_ID]
SCHEMA_VERSION = "cx_upload_ownership_postgres_smoke.v1"
SECRET_SOURCE_TEXT = "CX upload ownership PostgreSQL smoke source should not leak"


class StaticOwnerResolver:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def resolve_ownership_ref(
        self,
        ownership_ref: Mapping[str, Any],
        *,
        request_id: str,
        trace_id: str,
        ensure: bool = False,
    ) -> dict[str, object]:
        normalized = dict(ownership_ref)
        self.calls.append(
            {
                "ownership_ref": normalized,
                "request_id": request_id,
                "trace_id": trace_id,
                "ensure": ensure,
            }
        )
        return {
            "resolver_schema_version": "oa_subject_registry_resolver.v1",
            "resolution_status": "RESOLVED",
            "action": "verify",
            "tenant_ref": dict(normalized["tenant_ref"]),
            "owner_subject_ref": dict(normalized["owner_subject_ref"]),
            "uploaded_by_subject_ref": dict(normalized["uploaded_by_subject_ref"]),
        }


def run_cx_upload_ownership_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
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
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        run_service_migrations(SERVICE_ID, database_url=database_url, profile=profile)
        execution = _execute_upload_ownership_smoke(
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPEC.database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
                "NEX_CX_UPLOAD_OWNER_RESOLVER_MODE": UPLOAD_OWNER_RESOLVER_VERIFY,
            },
        )
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            **execution,
        }
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__, profile=profile)


def _execute_upload_ownership_smoke(
    *,
    database_url: str,
    runtime_environ: dict[str, str],
) -> dict[str, object]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    document_id: str | None = None
    source_file_id: str | None = None
    engine = build_engine(database_url)
    with tempfile.TemporaryDirectory(prefix="nex-cx-upload-ownership-smoke-") as temp_dir:
        storage_config = _storage_config(Path(temp_dir))
        resolver = StaticOwnerResolver()
        app = build_service_app(SERVICE_SPEC)
        persistence = attach_service_persistence_runtime(
            app,
            SERVICE_SPEC,
            environ=runtime_environ,
        )
        if persistence.api_session_factory is None:
            raise RuntimeError("CX PostgreSQL upload smoke session factory is unavailable")

        repository = SqlAlchemyCxContentRepository(
            persistence.api_session_factory,
            local_source_root=storage_config.source_root,
        )
        store = ContentIngestionStore(content_repository=repository)
        register_ingestion_routes(
            app,
            store=store,
            storage_config=storage_config,
            owner_resolver=resolver,
            owner_resolver_mode=UPLOAD_OWNER_RESOLVER_VERIFY,
        )
        client = TestClient(app)
        try:
            ownership_ref = _ownership_ref(request_id)
            response = client.post(
                "/api/v1/documents/uploads",
                json={
                    "filename": "cx-upload-ownership-postgres-smoke.txt",
                    "content_type": "text/plain",
                    "content_text": f"{SECRET_SOURCE_TEXT} request={request_id}",
                    "tenant_id": ownership_ref["tenant_ref"]["id"],
                    "owner_user_id": ownership_ref["owner_subject_ref"]["id"],
                    "ownership_ref": ownership_ref,
                },
                headers=_service_headers(trace_id=trace_id, request_id=request_id),
            )
            response.raise_for_status()
            payload = response.json()
            document_id = str(payload["document_id"])
            refs = store.get_content_ref(document_id)
            source_file_id = refs["source_file_id"] if refs is not None else None
            stored = _read_stored_upload_ownership(
                engine,
                document_id=document_id,
            )
            checks = {
                "api_status_created": response.status_code == 202,
                "runtime_mode": persistence.mode == "postgres",
                "resolver_called_once": len(resolver.calls) == 1,
                "resolver_verify_only": bool(resolver.calls)
                and resolver.calls[0]["ensure"] is False,
                "persisted_content_owner_refs": _content_owner_refs_match(
                    stored,
                    ownership_ref,
                ),
                "persisted_owner_acl_ref": _owner_acl_ref_matches(
                    stored,
                    ownership_ref,
                ),
                "source_checksum_verified": bool(stored.get("checksum_verified_at")),
                "source_file_path_materialized": Path(
                    payload["storage"]["source_storage_path"]
                ).exists(),
                "raw_payload_absent": _redaction_safe(
                    payload,
                    stored,
                    forbidden_fragments=[SECRET_SOURCE_TEXT],
                ),
            }
            if not all(checks.values()):
                raise RuntimeError("CX upload ownership PostgreSQL smoke checks failed")
            return {
                "document_id": document_id,
                "source_file_id": source_file_id,
                "checks": checks,
            }
        finally:
            _delete_smoke_upload_rows(
                engine,
                document_id=document_id,
                source_file_id=source_file_id,
            )


def _ownership_ref(request_id: str) -> dict[str, object]:
    suffix = request_id.split("-", maxsplit=1)[0]
    return {
        "ownership_schema_version": "cx_source_ownership_ref.v1",
        "tenant_ref": {"type": "oa.tenant", "id": f"tenant-smoke-{suffix}"},
        "owner_subject_ref": {"type": "oa.user", "id": f"owner-smoke-{suffix}"},
        "uploaded_by_subject_ref": {
            "type": "oa.user",
            "id": f"uploader-smoke-{suffix}",
        },
        "legacy": {
            "tenant_id": f"tenant-smoke-{suffix}",
            "owner_user_id": f"owner-smoke-{suffix}",
        },
        "compatibility_mode": "legacy_owner_fields_mapped_to_oa_subject_refs",
    }


def _read_stored_upload_ownership(
    engine: object,
    *,
    document_id: str,
) -> dict[str, object]:
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    co.content_object_id,
                    co.tenant_ref_type,
                    co.tenant_ref_id,
                    co.owner_subject_ref_type,
                    co.owner_subject_ref_id,
                    co.uploaded_by_subject_ref_type,
                    co.uploaded_by_subject_ref_id,
                    co.source_file_id,
                    sf.source_sha256,
                    sf.storage_backend,
                    sf.storage_key,
                    sf.checksum_verified_at,
                    acl.principal_ref_type,
                    acl.principal_ref_id,
                    acl.granted_by_subject_ref_type,
                    acl.granted_by_subject_ref_id
                FROM cx_content_objects co
                JOIN cx_source_files sf ON sf.source_file_id = co.source_file_id
                LEFT JOIN cx_content_acl_entries acl
                  ON acl.content_object_id = co.content_object_id
                 AND acl.permission = 'owner'
                WHERE co.content_object_id = :document_id
                """
            ),
            {"document_id": document_id},
        ).mappings().first()
    if row is None:
        raise RuntimeError("CX upload ownership smoke content object was not persisted")
    return dict(row)


def _content_owner_refs_match(
    stored: Mapping[str, object],
    ownership_ref: Mapping[str, Any],
) -> bool:
    return (
        stored.get("tenant_ref_type") == ownership_ref["tenant_ref"]["type"]
        and stored.get("tenant_ref_id") == ownership_ref["tenant_ref"]["id"]
        and stored.get("owner_subject_ref_type")
        == ownership_ref["owner_subject_ref"]["type"]
        and stored.get("owner_subject_ref_id") == ownership_ref["owner_subject_ref"]["id"]
        and stored.get("uploaded_by_subject_ref_type")
        == ownership_ref["uploaded_by_subject_ref"]["type"]
        and stored.get("uploaded_by_subject_ref_id")
        == ownership_ref["uploaded_by_subject_ref"]["id"]
    )


def _owner_acl_ref_matches(
    stored: Mapping[str, object],
    ownership_ref: Mapping[str, Any],
) -> bool:
    return (
        stored.get("principal_ref_type") == ownership_ref["owner_subject_ref"]["type"]
        and stored.get("principal_ref_id") == ownership_ref["owner_subject_ref"]["id"]
        and stored.get("granted_by_subject_ref_type")
        == ownership_ref["uploaded_by_subject_ref"]["type"]
        and stored.get("granted_by_subject_ref_id")
        == ownership_ref["uploaded_by_subject_ref"]["id"]
    )


def _delete_smoke_upload_rows(
    engine: object,
    *,
    document_id: str | None,
    source_file_id: str | None,
) -> None:
    with engine.begin() as connection:
        if document_id is not None:
            connection.execute(
                text(
                    """
                    DELETE FROM cx_content_acl_entries
                    WHERE content_object_id = :document_id
                    """
                ),
                {"document_id": document_id},
            )
            connection.execute(
                text(
                    """
                    DELETE FROM cx_content_objects
                    WHERE content_object_id = :document_id
                    """
                ),
                {"document_id": document_id},
            )
        if source_file_id is not None:
            connection.execute(
                text(
                    """
                    DELETE FROM cx_source_files
                    WHERE source_file_id = :source_file_id
                    """
                ),
                {"source_file_id": source_file_id},
            )


def _storage_config(temp_dir: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=temp_dir,
        source_root=temp_dir / "cx" / "source-files",
        extracted_markdown_root=temp_dir / "cx" / "extracted-markdown",
        extraction_temp_root=temp_dir / "cx" / "extraction-temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def _service_headers(*, trace_id: str, request_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience=SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _redaction_safe(
    *payloads: object,
    forbidden_fragments: list[str],
) -> bool:
    rendered = json.dumps(payloads, default=str, ensure_ascii=False)
    return all(fragment not in rendered for fragment in forbidden_fragments)


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
) -> dict[str, object]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }


def summary_line(evidence: dict[str, object]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"cx_upload_ownership_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "cx_upload_ownership_postgres_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']}"
        )
    return (
        "cx_upload_ownership_postgres_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional CX upload ownership PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_cx_upload_ownership_postgres_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False)
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
