#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
CX_PATH = ROOT / "services" / "nex-cx"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(CX_PATH))

from nex_cx.chunking import store_chunk_set  # noqa: E402
from nex_cx.ingestion import (  # noqa: E402
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    run_text_extraction_job,
)
from nex_cx.repository import SqlAlchemyCxContentRepository  # noqa: E402
from nex_runtime import (  # noqa: E402
    build_engine,
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


SMOKE_ENV = "NEX_CX_RETRIEVAL_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_CX_RETRIEVAL_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SCHEMA_VERSION = "cx_retrieval_postgres_smoke.v1"


def run_cx_retrieval_postgres_smoke(
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
        execution = _execute_retrieval_repository_smoke(database_url=database_url)
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


def _execute_retrieval_repository_smoke(*, database_url: str) -> dict[str, object]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    engine = build_engine(database_url)
    repository = SqlAlchemyCxContentRepository(build_session_factory(engine))
    store = ContentIngestionStore(content_repository=repository)
    document_id: str | None = None
    source_file_id: str | None = None
    retrieval_package_id: str | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="nex-cx-retrieval-smoke-") as temp_dir:
            storage_config = _storage_config(Path(temp_dir))
            source_text = (
                "CX retrieval PostgreSQL smoke source "
                f"{request_id} verifies hash-only evidence persistence."
            )
            query_text = "retrieval smoke query " + ("q" * 400)
            evidence_text = "retrieval smoke evidence " + ("e" * 400)
            document = build_upload_registration(
                {
                    "filename": "cx-retrieval-postgres-smoke.txt",
                    "content_type": "text/plain",
                    "content_text": source_text,
                },
                storage_config=storage_config,
                request_id=request_id,
                trace_id=trace_id,
            )
            saved_document = store.save_upload_registration(
                document,
                source_text=source_text,
            )
            document_id = str(saved_document["document_id"])
            refs = store.get_content_ref(document_id)
            source_file_id = refs["source_file_id"] if refs is not None else None
            extraction = run_text_extraction_job(
                saved_document["extraction"]["job_id"],
                store=store,
                storage_config=storage_config,
                request_id=request_id,
                trace_id=trace_id,
            )
            chunk_set = store_chunk_set(
                document_id=document_id,
                extraction=extraction,
                markdown_text=Path(extraction["extracted_markdown_path"]).read_text(
                    encoding="utf-8"
                ),
                store=store,
                storage_config=storage_config,
                request_id=request_id,
                trace_id=trace_id,
            )
            package = _retrieval_package(
                document_id=document_id,
                chunk=chunk_set["chunks"][0],
                request_id=request_id,
                trace_id=trace_id,
                query_text=query_text,
                evidence_text=evidence_text,
            )
            store.save_retrieval_package(package)
            retrieval_package_id = str(package["retrieval_package_id"])
            stored = _read_stored_retrieval_package(
                engine,
                retrieval_package_id=retrieval_package_id,
            )
            repository_round_trip = repository.get_retrieval_package_record(
                retrieval_package_id
            )
            dump = _read_smoke_retrieval_dump(
                engine,
                retrieval_package_id=retrieval_package_id,
            )
            checks = {
                "package_persisted": (
                    stored["retrieval_package_id"] == retrieval_package_id
                ),
                "evidence_persisted": stored["stored_evidence_count"] == 1,
                "query_hash_persisted": stored["query_text_sha256"]
                == _sha256_text(query_text),
                "query_preview_bounded": (
                    len(str(stored["query_text_preview"])) <= 240
                ),
                "evidence_hash_persisted": stored["evidence_text_sha256"]
                == _sha256_text(evidence_text),
                "final_score_persisted": stored["final_score"] == 0.9,
                "repository_round_trip": repository_round_trip is not None
                and repository_round_trip["evidence_count"] == 1,
                "raw_payload_absent": (
                    query_text not in dump
                    and evidence_text not in dump
                    and source_text not in dump
                ),
            }
            if not all(checks.values()):
                raise RuntimeError("CX retrieval PostgreSQL smoke checks failed")
            return {
                "retrieval_package_id": retrieval_package_id,
                "document_id": document_id,
                "evidence_count": stored["stored_evidence_count"],
                "checks": checks,
            }
    finally:
        _delete_smoke_retrieval_rows(
            engine,
            retrieval_package_id=retrieval_package_id,
            document_id=document_id,
            source_file_id=source_file_id,
        )


def _retrieval_package(
    *,
    document_id: str,
    chunk: dict[str, Any],
    request_id: str,
    trace_id: str,
    query_text: str,
    evidence_text: str,
) -> dict[str, object]:
    package_hash = _sha256_json(
        {
            "document_id": document_id,
            "chunk_id": chunk["chunk_id"],
            "query_text": query_text,
            "request_id": request_id,
        }
    )
    return {
        "retrieval_package_schema_version": "cx_retrieval_context_package.v1",
        "retrieval_package_id": str(uuid4()),
        "package_hash": package_hash,
        "status": "READY",
        "trace_id": trace_id,
        "request_id": request_id,
        "query_text": query_text,
        "query_embedding_snapshot": {
            "provided": True,
            "embedding_sha256": _sha256_json({"embedding": [0.1, 0.2, 0.3]}),
            "vector_dimension": 3,
        },
        "purpose": "grounded_answer",
        "retrieval_profile": {
            "quality_policy": {
                "policy_id": "weighted_rrf_vector_bm25_v1",
                "policy_version": "2026-08-09",
                "policy_hash": _sha256_json({"policy": "weighted_rrf_v1"}),
                "policy_source": "ag_registry_active",
                "ranker_mix": "weighted_rrf_vector_bm25_v1",
            }
        },
        "permission_snapshot": {
            "actor_type": "service",
            "actor_id": "cx-retrieval-postgres-smoke",
            "scope_applied": {"type": "document_ids", "document_ids": [document_id]},
            "visible_document_count": 1,
        },
        "evidence_items": [
            {
                "evidence_id": str(uuid4()),
                "rank": 1,
                "content_object_id": document_id,
                "content_version_id": chunk["text_sha256"],
                "chunk_id": chunk["chunk_id"],
                "chunk_policy_id": "chunk_1000_100",
                "source_anchor": {
                    "type": "character_range",
                    "start_offset": chunk["start_offset"],
                    "end_offset": chunk["end_offset"],
                },
                "citation_label": "[1]",
                "text": evidence_text,
                "neighbor_context": [],
                "scores": {
                    "bm25_score": 1.0,
                    "vector_score": 0.8,
                    "final_score": 0.9,
                },
                "matched_terms": ["retrieval", "smoke"],
                "permission_result": {
                    "visible": True,
                    "reason": "smoke_scope",
                },
                "quality_flags": [],
            }
        ],
        "source_summary": {
            "source_count": 1,
            "document_count": 1,
            "chunk_count": 1,
            "source_types": ["cx.document"],
        },
        "score_summary": {
            "best_score": 0.9,
            "score_spread": 0.0,
            "ranker_mix": "weighted_rrf_vector_bm25_v1",
            "rerank_state": "NOT_APPLIED",
        },
        "warnings": [],
        "no_answer_reason": None,
        "created_at": "2026-08-09T00:00:00Z",
        "updated_at": "2026-08-09T00:00:00Z",
    }


def _read_stored_retrieval_package(
    engine: object,
    *,
    retrieval_package_id: str,
) -> dict[str, object]:
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    package.retrieval_package_id,
                    package.query_text_sha256,
                    package.query_text_preview,
                    package.evidence_count,
                    evidence.evidence_text_sha256,
                    evidence.evidence_text_preview,
                    evidence.final_score,
                    count(evidence.evidence_id) OVER (
                        PARTITION BY package.retrieval_package_id
                    ) AS stored_evidence_count
                FROM cx_retrieval_packages AS package
                LEFT JOIN cx_retrieval_evidence_items AS evidence
                  ON evidence.retrieval_package_id = package.retrieval_package_id
                WHERE package.retrieval_package_id = :retrieval_package_id
                ORDER BY evidence.rank ASC
                """
            ),
            {"retrieval_package_id": retrieval_package_id},
        ).mappings().first()
    if row is None:
        raise RuntimeError("stored retrieval package was not found")
    return {
        "retrieval_package_id": str(row["retrieval_package_id"]),
        "query_text_sha256": row["query_text_sha256"],
        "query_text_preview": row["query_text_preview"],
        "evidence_count": int(row["evidence_count"]),
        "evidence_text_sha256": row["evidence_text_sha256"],
        "evidence_text_preview": row["evidence_text_preview"],
        "final_score": float(row["final_score"] or 0.0),
        "stored_evidence_count": int(row["stored_evidence_count"] or 0),
    }


def _read_smoke_retrieval_dump(
    engine: object,
    *,
    retrieval_package_id: str,
) -> str:
    with engine.begin() as connection:
        package_rows = connection.execute(
            text(
                """
                SELECT query_text_preview, source_summary, score_summary
                FROM cx_retrieval_packages
                WHERE retrieval_package_id = :retrieval_package_id
                """
            ),
            {"retrieval_package_id": retrieval_package_id},
        ).fetchall()
        evidence_rows = connection.execute(
            text(
                """
                SELECT evidence_text_preview, scores, matched_terms, permission_result
                FROM cx_retrieval_evidence_items
                WHERE retrieval_package_id = :retrieval_package_id
                """
            ),
            {"retrieval_package_id": retrieval_package_id},
        ).fetchall()
    return str(package_rows) + str(evidence_rows)


def _delete_smoke_retrieval_rows(
    engine: object,
    *,
    retrieval_package_id: str | None,
    document_id: str | None,
    source_file_id: str | None,
) -> None:
    with engine.begin() as connection:
        if retrieval_package_id is not None:
            connection.execute(
                text(
                    """
                    DELETE FROM cx_retrieval_evidence_items
                    WHERE retrieval_package_id = :retrieval_package_id
                    """
                ),
                {"retrieval_package_id": retrieval_package_id},
            )
            connection.execute(
                text(
                    """
                    DELETE FROM cx_retrieval_packages
                    WHERE retrieval_package_id = :retrieval_package_id
                    """
                ),
                {"retrieval_package_id": retrieval_package_id},
            )
        if document_id is not None:
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
        return f"cx_retrieval_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "cx_retrieval_postgres_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']}"
        )
    return (
        "cx_retrieval_postgres_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_text(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional CX retrieval package PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    load_env_file(ROOT / ".env.local")
    evidence = run_cx_retrieval_postgres_smoke()
    output = (
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False)
    )
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
