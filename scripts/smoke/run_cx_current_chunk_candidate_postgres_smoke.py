#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import psycopg


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.lexical_candidates import PostgresLexicalCandidateStore  # noqa: E402
from nex_runtime import build_engine, build_session_factory, redact_database_url  # noqa: E402
from run_cx_lexical_candidate_postgres_smoke import (  # noqa: E402
    _cleanup,
    _fixture,
    _seed_fixture,
)
from run_migrations import run_service_migrations, service_database_url  # noqa: E402


SCHEMA_VERSION = "cx_current_chunk_candidate_postgres_smoke.v1"
SMOKE_ENV = "NEX_CX_CURRENT_CHUNK_CANDIDATE_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_CX_CURRENT_CHUNK_CANDIDATE_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = "nex-cx"
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"
TENANT_ID = "s136-lineage-tenant"
OWNER_ID = "s136-lineage-owner"
CURRENT_TERM = "currentlineage"


def run_cx_current_chunk_candidate_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    profile = env.get(PROFILE_ENV, "test")
    if profile != "test":
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
                "current_chunk_candidate_smoke_failed",
                execution["failed_checks"],
                execution=execution,
            )
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
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
    fixture = _fixture(owner_id=OWNER_ID, lifecycle_status="ACTIVE", counts=(4,))
    checks: dict[str, bool] = {}
    engine = None
    with psycopg.connect(_psycopg_url(database_url), autocommit=True) as connection:
        try:
            _seed_fixture(connection, fixture, tenant_id=TENANT_ID)
            current = _seed_current_generation(connection, fixture)
            engine = build_engine(database_url)
            store = PostgresLexicalCandidateStore(build_session_factory(engine))
            stale = store.search(
                access_context=_context(owner_id=OWNER_ID),
                query_terms=["alpha"],
                content_object_ids=[str(fixture.content)],
                limit=10,
            )
            fresh = store.search(
                access_context=_context(owner_id=OWNER_ID),
                query_terms=[CURRENT_TERM],
                content_object_ids=[str(fixture.content)],
                limit=10,
            )
            foreign = store.search(
                access_context=_context(owner_id="s136-other-owner"),
                query_terms=[CURRENT_TERM],
                content_object_ids=[str(fixture.content)],
                limit=10,
            )
            checks.update(
                {
                    "stale_chunk_set_excluded": stale == [],
                    "current_chunk_set_selected": (
                        len(fresh) == 1
                        and fresh[0]["chunk_set_id"] == str(current["chunk_set_id"])
                        and fresh[0]["chunk_id"] == str(current["chunk_id"])
                    ),
                    "current_term_matched": (
                        fresh[0]["matched_terms"] == [CURRENT_TERM] if fresh else False
                    ),
                    "foreign_owner_excluded": foreign == [],
                }
            )
        finally:
            if engine is not None:
                engine.dispose()
            _cleanup(connection, [fixture])
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
        "candidate_generation": "latest_chunk_set_only",
    }


def _seed_current_generation(connection: Any, fixture: Any) -> dict[str, Any]:  # pragma: no cover
    observed_at = datetime.now(UTC) + timedelta(seconds=1)
    chunk_set_id = uuid4()
    chunk_id = uuid4()
    term_id = uuid4()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cx_chunk_sets (
                chunk_set_id, content_object_id, extraction_artifact_id,
                chunk_policy_id, chunk_size, chunk_overlap,
                source_markdown_sha256, chunk_count, created_at
            ) VALUES (%s, %s, %s, '1000_100', 1000, 100, %s, 1, %s)
            """,
            (
                chunk_set_id,
                fixture.content,
                fixture.artifact,
                _digest(f"current:{fixture.content}"),
                observed_at,
            ),
        )
        cursor.execute(
            """
            INSERT INTO cx_chunks (
                chunk_id, chunk_set_id, content_object_id, ordinal,
                start_offset, end_offset, char_count, text_sha256,
                text_preview, created_at
            ) VALUES (%s, %s, %s, 0, 0, 13, 13, %s, %s, %s)
            """,
            (
                chunk_id,
                chunk_set_id,
                fixture.content,
                _digest("current chunk"),
                "current chunk",
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
                      'korean_mixed_v1', true, %s, 1, %s)
            """,
            (term_id, chunk_set_id, CURRENT_TERM, observed_at),
        )
        cursor.execute(
            """
            INSERT INTO cx_lexical_postings (
                lexical_posting_id, lexical_term_id, chunk_id,
                occurrence_count, created_at
            ) VALUES (%s, %s, %s, 3, %s)
            """,
            (uuid4(), term_id, chunk_id, observed_at),
        )
    return {"chunk_set_id": chunk_set_id, "chunk_id": chunk_id}


def _context(*, owner_id: str) -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id=TENANT_ID,
        subject_id=owner_id,
        request_id="s136-current-lineage-smoke",
        trace_id="13540000000000000000000000000001",
        scopes=("service:call",),
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
        return f"cx_current_chunk_candidate_postgres_smoke=skipped reason={SMOKE_ENV}"
    if status == "pass":
        return (
            "cx_current_chunk_candidate_postgres_smoke=pass "
            f"checks={result['check_count']}/{result['check_count']} "
            "lineage=latest_chunk_set_only"
        )
    return (
        "cx_current_chunk_candidate_postgres_smoke=fail "
        f"error={(result.get('error') or {}).get('code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_current_chunk_candidate_postgres_smoke()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
