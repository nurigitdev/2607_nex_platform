#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import psycopg


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "scripts" / "db",
):
    sys.path.insert(0, str(path))

from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.lexical_candidates import PostgresLexicalCandidateStore  # noqa: E402
from nex_runtime import (  # noqa: E402
    build_engine,
    build_session_factory,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SCHEMA_VERSION = "cx_lexical_candidate_postgres_smoke.v1"
SMOKE_ENV = "NEX_CX_LEXICAL_CANDIDATE_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_CX_LEXICAL_CANDIDATE_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"
TENANT_ID = "s95-lexical-tenant"
OWNER_ID = "s95-lexical-owner"


def run_cx_lexical_candidate_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure("profile_not_allowed", f"{PROFILE_ENV} must be test.")

    database_url = ""
    try:
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        if not _target_url_allowed(database_url):
            return _failure("target_not_allowed", "CX test database target is required.")
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_smoke(database_url)
        if execution["failed_checks"]:
            return _failure(
                "lexical_candidate_smoke_failed",
                execution["failed_checks"],
                execution=execution,
            )
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": service_database_env(SERVICE_ID, profile=profile),
            "redacted_database_url": redact_database_url(database_url),
            "migration": {
                "applied": list(migration.applied),
                "skipped": list(migration.skipped),
            },
            "remote_provider_required": False,
            **execution,
        }
    except Exception as exc:  # pragma: no cover - protected PostgreSQL evidence
        return _failure(
            "execution_failed",
            exc.__class__.__name__,
            redacted_database_url=(
                redact_database_url(database_url) if database_url else None
            ),
        )


def _execute_smoke(database_url: str) -> dict[str, Any]:  # pragma: no cover
    fixtures = [
        _fixture(owner_id=OWNER_ID, lifecycle_status="ACTIVE", counts=(3, 1)),
        _fixture(owner_id="s95-foreign-owner", lifecycle_status="ACTIVE", counts=(20,)),
        _fixture(owner_id=OWNER_ID, lifecycle_status="DELETED", counts=(20,)),
    ]
    checks: dict[str, bool] = {}
    engine = None
    with psycopg.connect(_psycopg_url(database_url), autocommit=True) as connection:
        try:
            for fixture in fixtures:
                _seed_fixture(connection, fixture)
            engine = build_engine(database_url)
            store = PostgresLexicalCandidateStore(build_session_factory(engine))
            context = CxAccessContext(
                caller_service_id="nex-cx",
                tenant_id=TENANT_ID,
                subject_id=OWNER_ID,
                request_id="s95-lexical-smoke",
                trace_id="94300000000000000000000000000001",
                scopes=("service:call",),
            )
            all_owner = store.search(
                access_context=context,
                query_terms=["alpha"],
                limit=10,
            )
            active = fixtures[0]
            scoped = store.search(
                access_context=context,
                query_terms=["alpha"],
                content_object_ids=[str(active.content)],
                limit=10,
            )
            foreign_scope = store.search(
                access_context=context,
                query_terms=["alpha"],
                content_object_ids=[str(fixtures[1].content)],
                limit=10,
            )
            returned_ids = {item["content_object_id"] for item in all_owner}
            checks.update(
                {
                    "owner_active_candidates_only": len(all_owner) == 2
                    and returned_ids == {str(active.content)},
                    "cross_owner_excluded": str(fixtures[1].content) not in returned_ids,
                    "inactive_excluded": str(fixtures[2].content) not in returned_ids,
                    "bm25_frequency_ranking": all_owner[0]["chunk_id"]
                    == str(active.chunks[0]),
                    "positive_bm25_scores": all(
                        item["bm25_score"] > 0 for item in all_owner
                    ),
                    "matched_terms_returned": all(
                        item["matched_terms"] == ["alpha"] for item in all_owner
                    ),
                    "explicit_owner_scope": len(scoped) == 2,
                    "foreign_explicit_scope_empty": foreign_scope == [],
                }
            )
        finally:
            if engine is not None:
                engine.dispose()
            _cleanup(connection, fixtures)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM cx_content_objects WHERE tenant_ref_id = %s",
                    (TENANT_ID,),
                )
                checks["cleanup_complete"] = cursor.fetchone() == (0,)
    return {
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "check_count": len(checks),
        "candidate_count": 2,
        "ranking": "bm25",
    }


def _fixture(
    *,
    owner_id: str,
    lifecycle_status: str,
    counts: tuple[int, ...],
) -> SimpleNamespace:
    content = uuid4()
    return SimpleNamespace(
        source=uuid4(),
        content=content,
        upload=uuid4(),
        artifact=uuid4(),
        chunk_set=uuid4(),
        chunks=tuple(uuid4() for _ in counts),
        term=uuid4(),
        owner_id=owner_id,
        lifecycle_status=lifecycle_status,
        counts=counts,
        source_hash=_digest(f"source:{content}"),
        markdown_hash=_digest(f"markdown:{content}"),
    )


def _seed_fixture(connection: Any, fixture: SimpleNamespace) -> None:  # pragma: no cover
    observed_at = datetime.now(UTC)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cx_source_files (
                source_file_id, source_sha256, size_bytes, content_type,
                storage_uri, storage_backend, storage_key,
                stored_filename, stored_extension, created_at
            ) VALUES (%s, %s, 16, 'text/markdown', %s, 'local_filesystem',
                      %s, %s, '.md', %s)
            """,
            (
                fixture.source,
                fixture.source_hash,
                f"cx-source://{fixture.source}",
                (
                    f"{observed_at:%Y%m%d}/{fixture.source_hash[:2]}/"
                    f"{fixture.source_hash[2:4]}/{fixture.source}.md"
                ),
                f"{fixture.source}.md",
                observed_at,
            ),
        )
        cursor.execute(
            """
            INSERT INTO cx_content_objects (
                content_object_id, tenant_id, owner_user_id, source_file_id,
                source_sha256, upload_id, original_filename, content_type,
                size_bytes, lifecycle_status, tenant_ref_type, tenant_ref_id,
                owner_subject_ref_type, owner_subject_ref_id,
                uploaded_by_subject_ref_type, uploaded_by_subject_ref_id,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, 's95.md', 'text/markdown', 16, %s,
                'oa.tenant', %s, 'oa.user', %s, 'oa.user', %s, %s, %s
            )
            """,
            (
                fixture.content,
                TENANT_ID,
                fixture.owner_id,
                fixture.source,
                fixture.source_hash,
                fixture.upload,
                fixture.lifecycle_status,
                TENANT_ID,
                fixture.owner_id,
                fixture.owner_id,
                observed_at,
                observed_at,
            ),
        )
        cursor.execute(
            """
            INSERT INTO cx_extraction_artifacts (
                extraction_artifact_id, content_object_id, source_file_id,
                extractor_name, extractor_version, markdown_sha256,
                markdown_storage_uri, markdown_char_count, created_at, updated_at
            ) VALUES (%s, %s, %s, 's95-smoke', '1', %s, %s, 16, %s, %s)
            """,
            (
                fixture.artifact,
                fixture.content,
                fixture.source,
                fixture.markdown_hash,
                f"cx-private://markdown/{fixture.artifact}",
                observed_at,
                observed_at,
            ),
        )
        cursor.execute(
            """
            INSERT INTO cx_chunk_sets (
                chunk_set_id, content_object_id, extraction_artifact_id,
                chunk_policy_id, chunk_size, chunk_overlap,
                source_markdown_sha256, chunk_count, created_at
            ) VALUES (%s, %s, %s, '1000_100', 1000, 100, %s, %s, %s)
            """,
            (
                fixture.chunk_set,
                fixture.content,
                fixture.artifact,
                fixture.markdown_hash,
                len(fixture.chunks),
                observed_at,
            ),
        )
        for ordinal, chunk_id in enumerate(fixture.chunks):
            cursor.execute(
                """
                INSERT INTO cx_chunks (
                    chunk_id, chunk_set_id, content_object_id, ordinal,
                    start_offset, end_offset, char_count, text_sha256,
                    text_preview, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, 8, %s, %s, %s)
                """,
                (
                    chunk_id,
                    fixture.chunk_set,
                    fixture.content,
                    ordinal,
                    ordinal * 10,
                    ordinal * 10 + 8,
                    _digest(f"chunk:{chunk_id}"),
                    f"alpha chunk {ordinal}",
                    observed_at,
                ),
            )
        cursor.execute(
            """
            INSERT INTO cx_lexical_terms (
                lexical_term_id, chunk_set_id, tokenizer_requested,
                tokenizer_used, tokenizer_fallback, fallback_used,
                term, document_frequency, created_at
            ) VALUES (%s, %s, 'mecab_ko', 'korean_mixed_v1',
                      'korean_mixed_v1', true, 'alpha', %s, %s)
            """,
            (fixture.term, fixture.chunk_set, len(fixture.chunks), observed_at),
        )
        for chunk_id, count in zip(fixture.chunks, fixture.counts, strict=True):
            cursor.execute(
                """
                INSERT INTO cx_lexical_postings (
                    lexical_posting_id, lexical_term_id, chunk_id,
                    occurrence_count, created_at
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (uuid4(), fixture.term, chunk_id, count, observed_at),
            )


def _cleanup(connection: Any, fixtures: list[SimpleNamespace]) -> None:  # pragma: no cover
    with connection.cursor() as cursor:
        for fixture in fixtures:
            cursor.execute(
                "DELETE FROM cx_content_objects WHERE content_object_id = %s",
                (fixture.content,),
            )
            cursor.execute(
                "DELETE FROM cx_source_files WHERE source_file_id = %s",
                (fixture.source,),
            )


def _psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(_psycopg_url(database_url))
    return (
        unquote(parsed.username or "") == EXPECTED_ROLE
        and parsed.path.lstrip("/") == EXPECTED_DATABASE
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _failure(code: str, detail: Any, **extra: Any) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "error": {"code": code, "detail": detail},
        **extra,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status") or "FAIL").lower()
    if status == "skipped":
        return f"cx_lexical_candidate_postgres_smoke=skipped reason={SMOKE_ENV}"
    if status == "pass":
        return (
            "cx_lexical_candidate_postgres_smoke=pass "
            f"checks={result['check_count']}/{result['check_count']} "
            f"candidates={result['candidate_count']} ranking=bm25 remote_required=False"
        )
    return (
        "cx_lexical_candidate_postgres_smoke=fail "
        f"error={(result.get('error') or {}).get('code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_lexical_candidate_postgres_smoke()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
