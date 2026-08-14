#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
CX_PATH = ROOT / "services" / "nex-cx"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(CX_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_cx.ingestion import (  # noqa: E402
    UPLOAD_OWNER_RESOLVER_DISABLED,
    ContentIngestionStore,
    register_ingestion_routes,
)
from nex_cx.repository import SqlAlchemyCxContentRepository  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_engine,
    build_service_app,
    load_env_file,
    redact_database_url,
)
from run_cx_document_library_postgres_smoke import _migration_evidence  # noqa: E402
from run_cx_extractor_backend_gap_audit import (  # noqa: E402
    sample_docx_bytes,
    sample_pdf_bytes,
    sample_pptx_bytes,
    sample_xlsx_bytes,
)
from run_cx_upload_ownership_postgres_smoke import (  # noqa: E402
    _redaction_safe,
    _service_headers,
    _storage_config,
)
from run_cx_uploaded_source_extraction_postgres_smoke import (  # noqa: E402
    _delete_uploaded_source_extraction_rows,
    _read_extraction_artifact_observation,
    _read_source_file_observation,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SMOKE_ENV = "NEX_CX_REAL_DOCUMENT_EXTRACTION_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_CX_REAL_DOCUMENT_EXTRACTION_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SERVICE_SPEC = SERVICE_SPECS[SERVICE_ID]
SCHEMA_VERSION = "cx_real_document_extraction_postgres_smoke.v1"
SECRET_MARKER_PREFIX = "CX real document extraction PostgreSQL smoke marker"


DocumentBytesFactory = Callable[[str], bytes]


REAL_DOCUMENT_FORMATS: tuple[dict[str, object], ...] = (
    {
        "source_format": "pdf",
        "filename": "cx-real-document-extraction-smoke.pdf",
        "content_type": "application/pdf",
        "expected_mode": "pdf_to_markdown",
        "bytes_factory": sample_pdf_bytes,
    },
    {
        "source_format": "docx",
        "filename": "cx-real-document-extraction-smoke.docx",
        "content_type": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        "expected_mode": "docx_to_markdown",
        "bytes_factory": sample_docx_bytes,
    },
    {
        "source_format": "pptx",
        "filename": "cx-real-document-extraction-smoke.pptx",
        "content_type": (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
        "expected_mode": "pptx_to_markdown",
        "bytes_factory": sample_pptx_bytes,
    },
    {
        "source_format": "xlsx",
        "filename": "cx-real-document-extraction-smoke.xlsx",
        "content_type": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        "expected_mode": "xlsx_to_markdown",
        "bytes_factory": sample_xlsx_bytes,
    },
)


def run_cx_real_document_extraction_postgres_smoke(
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
        migration_result = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_real_document_extraction_smoke(
            database_env=database_env,
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPEC.database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            "migration": _migration_evidence(migration_result),
            **execution,
        }
        assert_evidence_redacted(evidence)
        return evidence
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__, profile=profile)


def _execute_real_document_extraction_smoke(
    *,
    database_env: str,
    database_url: str,
    runtime_environ: dict[str, str],
) -> dict[str, object]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.split("-", maxsplit=1)[0]
    tenant_id = f"tenant-real-document-extraction-{suffix}"
    owner_user_id = f"owner-real-document-extraction-{suffix}"
    engine = build_engine(database_url)
    tracked_rows: list[dict[str, str | None]] = []
    result: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="nex-cx-real-document-extraction-smoke-") as temp_dir:
        storage_config = _storage_config(Path(temp_dir))
        app = build_service_app(SERVICE_SPEC)
        persistence = attach_service_persistence_runtime(
            app,
            SERVICE_SPEC,
            environ=runtime_environ,
        )
        if persistence.api_session_factory is None:
            raise RuntimeError(
                "CX PostgreSQL real-document extraction smoke session factory is unavailable"
            )

        repository = SqlAlchemyCxContentRepository(
            persistence.api_session_factory,
            local_source_root=storage_config.source_root,
        )
        store = ContentIngestionStore(content_repository=repository)
        register_ingestion_routes(
            app,
            store=store,
            storage_config=storage_config,
            owner_resolver_mode=UPLOAD_OWNER_RESOLVER_DISABLED,
            database_env=database_env,
            redacted_database_url=redact_database_url(database_url),
            source_kind="postgres-read",
        )
        client = TestClient(app)
        try:
            observations = [
                _run_one_format_smoke(
                    spec=spec,
                    client=client,
                    store=store,
                    engine=engine,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    trace_id=trace_id,
                    request_id=request_id,
                    tracked_rows=tracked_rows,
                )
                for spec in REAL_DOCUMENT_FORMATS
            ]
            evidence_payload = {"observations": observations}
            checks = {
                "runtime_mode": persistence.mode == "postgres",
                "format_count": len(observations) == len(REAL_DOCUMENT_FORMATS),
                "all_uploads_created": all(
                    item["upload_status"] == "CREATED" for item in observations
                ),
                "all_runtime_source_bytes_evicted": all(
                    item["runtime_source_bytes_evicted"] is True
                    for item in observations
                ),
                "all_materialized_sources_verified": all(
                    item["source_checksum_verified"] is True for item in observations
                ),
                "all_extractions_succeeded": all(
                    item["extraction_status"] == "SUCCEEDED" for item in observations
                ),
                "all_expected_modes_used": all(
                    item["expected_mode_used"] is True for item in observations
                ),
                "all_private_markers_seen": all(
                    item["private_marker_seen"] is True for item in observations
                ),
                "all_artifacts_persisted": all(
                    item["artifact_count"] == 1 for item in observations
                ),
                "all_artifact_hashes_match": all(
                    item["markdown_sha256_matches"] is True for item in observations
                ),
                "evidence_redacted": _redaction_safe(
                    evidence_payload,
                    forbidden_fragments=[
                        SECRET_MARKER_PREFIX,
                        str(storage_config.source_root),
                        "source_storage_path",
                    ],
                ),
            }
            if not all(checks.values()):
                raise RuntimeError(
                    "CX real-document extraction PostgreSQL smoke checks failed"
                )
            result = {
                "format_count": len(observations),
                "formats": [
                    {
                        "source_format": item["source_format"],
                        "extractor_mode": item["extractor_mode"],
                        "artifact_count": item["artifact_count"],
                        "markdown_char_count": item["markdown_char_count"],
                    }
                    for item in observations
                ],
                "db_observations": {
                    "extraction_artifact_count": sum(
                        int(item["artifact_count"]) for item in observations
                    ),
                    "source_checksum_verified_count": sum(
                        1
                        for item in observations
                        if item["source_checksum_verified"] is True
                    ),
                },
                "checks": checks,
            }
        finally:
            result["cleanup_observations"] = [
                _delete_uploaded_source_extraction_rows(
                    engine,
                    document_id=item["document_id"],
                    source_file_id=item["source_file_id"],
                )
                for item in tracked_rows
            ]
    return result


def _run_one_format_smoke(
    *,
    spec: dict[str, object],
    client: TestClient,
    store: ContentIngestionStore,
    engine: object,
    tenant_id: str,
    owner_user_id: str,
    trace_id: str,
    request_id: str,
    tracked_rows: list[dict[str, str | None]],
) -> dict[str, object]:
    source_format = str(spec["source_format"])
    marker = f"{SECRET_MARKER_PREFIX}: {source_format} request={request_id}"
    bytes_factory = spec["bytes_factory"]
    source_bytes = bytes_factory(marker) if callable(bytes_factory) else b""
    upload_response = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": spec["filename"],
            "content_type": spec["content_type"],
            "content_base64": base64.b64encode(source_bytes).decode("ascii"),
            "tenant_id": tenant_id,
            "owner_user_id": f"{owner_user_id}-{source_format}",
        },
        headers=_service_headers(trace_id=trace_id, request_id=str(uuid4())),
    )
    upload_response.raise_for_status()
    upload = upload_response.json()
    document_id = str(upload["document_id"])
    upload_id = str(upload["upload_id"])
    refs = store.get_content_ref(document_id)
    source_file_id = refs["source_file_id"] if refs is not None else None
    tracked_rows.append(
        {
            "document_id": document_id,
            "source_file_id": source_file_id,
        }
    )
    source_path = Path(upload["storage"]["source_storage_path"])
    store.source_bytes.pop(upload_id, None)
    store.source_texts.pop(upload_id, None)

    extraction_response = client.post(
        f"/api/v1/jobs/{upload['extraction']['job_id']}/run",
        headers=_service_headers(trace_id=trace_id, request_id=str(uuid4())),
    )
    extraction_response.raise_for_status()
    extraction = extraction_response.json()
    markdown_text = Path(extraction["extracted_markdown_path"]).read_text(
        encoding="utf-8"
    )
    artifact_observation = _read_extraction_artifact_observation(
        engine,
        document_id=document_id,
        source_file_id=source_file_id,
        markdown_sha256=extraction["extracted_markdown_sha256"],
    )
    source_observation = _read_source_file_observation(
        engine,
        source_file_id=source_file_id,
    )
    return {
        "source_format": source_format,
        "upload_status": upload["dedupe"]["status"],
        "runtime_source_bytes_evicted": not store.source_bytes_available(upload_id),
        "materialized_source_exists": source_path.exists(),
        "source_checksum_verified": source_observation["checksum_verified"],
        "extraction_status": extraction["status"],
        "extractor_mode": extraction["extractor"]["mode"],
        "expected_mode_used": extraction["extractor"]["mode"] == spec["expected_mode"],
        "private_marker_seen": marker in markdown_text,
        "artifact_count": artifact_observation["artifact_count"],
        "markdown_sha256_matches": artifact_observation["markdown_sha256_matches"],
        "markdown_char_count": extraction["markdown_char_count"],
    }


def assert_evidence_redacted(evidence: object) -> None:
    rendered = json.dumps(evidence, default=str, ensure_ascii=False)
    forbidden = [
        SECRET_MARKER_PREFIX,
        "source_storage_path",
        "nex-cx-real-document-extraction-smoke-",
        "/data/nex-platform",
    ]
    for fragment in forbidden:
        if fragment in rendered:
            raise ValueError("CX real-document extraction smoke evidence is not redacted.")


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
        return f"cx_real_document_extraction_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "cx_real_document_extraction_postgres_smoke=pass "
            f"profile={evidence['profile']} "
            f"db_env={evidence['database_env']} "
            f"formats={evidence['format_count']} "
            f"artifacts={evidence['db_observations']['extraction_artifact_count']}"
        )
    return (
        "cx_real_document_extraction_postgres_smoke=fail "
        f"profile={evidence.get('profile')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the protected CX real-document extraction PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_env_file(ROOT / ".env")
    args = build_parser().parse_args(argv)
    evidence = run_cx_real_document_extraction_postgres_smoke()
    if args.output:
        serialized = json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{serialized}\n", encoding="utf-8")
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
