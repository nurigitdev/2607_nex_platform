#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
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
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_cx.vector_index_freshness import (  # noqa: E402
    build_embedding_profile,
    build_source_snapshot,
    build_vector_index_manifest,
    mark_vector_index_ready,
)
from nex_cx.vector_index_reconciliation import (  # noqa: E402
    admit_vector_rebuild,
    reconcile_vector_index,
)
from nex_cx.vector_index_repository import SqlAlchemyVectorIndexRepository  # noqa: E402
from nex_runtime import build_engine, build_session_factory, redact_database_url  # noqa: E402
from run_cx_pgvector_adapter_postgres_smoke import _digest, _seed_fixture  # noqa: E402
from run_migrations import (  # noqa: E402
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SCHEMA_VERSION = "cx_vector_reconciliation_postgres_smoke.v1"
SMOKE_ENV = "NEX_CX_VECTOR_RECONCILIATION_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_CX_VECTOR_RECONCILIATION_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"


def run_cx_vector_reconciliation_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {"status": "SKIPPED", "smoke_schema_version": SCHEMA_VERSION,
                "skip_reason": f"{SMOKE_ENV} is not enabled."}
    if env.get(PROFILE_ENV, DEFAULT_PROFILE) != DEFAULT_PROFILE:
        return _failure("profile_not_allowed", f"{PROFILE_ENV} must be test.")
    database_url = ""
    try:
        database_url = service_database_url(SERVICE_ID, profile="test", environ=env)
        database_env = service_database_env(SERVICE_ID, profile="test")
        if not _target_url_allowed(database_url):
            return _failure("target_not_allowed", "CX test database target is required.")
        migration = run_service_migrations(
            SERVICE_ID, database_url=database_url, profile="test"
        )
        execution = _execute_smoke(database_url)
        if execution["failed_checks"]:
            return _failure("reconciliation_smoke_failed", execution["failed_checks"])
        return {
            "status": "PASS",
            "smoke_schema_version": SCHEMA_VERSION,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            "migration_applied": list(migration.applied),
            "remote_embedding_required": False,
            **execution,
        }
    except Exception as exc:  # pragma: no cover - protected PostgreSQL evidence
        return _failure("execution_failed", exc.__class__.__name__)


def _execute_smoke(database_url: str) -> dict[str, Any]:  # pragma: no cover
    ids = SimpleNamespace(
        source=uuid4(), content=uuid4(), upload=uuid4(), artifact=uuid4(),
        chunk_set=uuid4(), chunk=uuid4(),
    )
    now = datetime.now(UTC)
    source_hash = _digest(f"source:{ids.content}")
    markdown_hash = _digest(f"markdown:{ids.content}")
    source = build_source_snapshot(
        chunk_set_id=str(ids.chunk_set), chunk_policy_id="1000_100",
        source_markdown_sha256=markdown_hash,
        chunks=[{"chunk_id": str(ids.chunk), "ordinal": 0,
                 "text_sha256": _digest(f"chunk:{ids.chunk}")}],
    )
    profile = build_embedding_profile(
        provider_alias="mock-s94", model_profile_id="Qwen3-Embedding-4B",
        model_revision="bf16", deployment_id="mock-local", vector_dimension=2560,
    )
    manifest = build_vector_index_manifest(
        content_object_id=str(ids.content),
        tenant_ref={"type": "oa.tenant", "id": "s94-adapter-tenant"},
        owner_subject_ref={"type": "oa.user", "id": "s94-adapter-owner"},
        source_snapshot=source, embedding_profile=profile,
        trace_id="s94-adapter-trace", request_id="s94-adapter-request",
        observed_at=now.isoformat(),
    )
    checks: dict[str, bool] = {}
    with psycopg.connect(database_url, autocommit=True) as connection:
        _seed_fixture(
            connection, ids=ids, manifest=manifest, source_hash=source_hash,
            markdown_hash=markdown_hash, observed_at=now,
        )
        engine = build_engine(database_url)
        repository = SqlAlchemyVectorIndexRepository(build_session_factory(engine))
        try:
            ready = mark_vector_index_ready(
                manifest,
                payload_receipts=[{
                    "chunk_id": str(ids.chunk), "embedding_sha256": "7" * 64,
                    "vector_dimension": 2560,
                    "storage_uri": f"cx-private://pgvector/{uuid4()}",
                }],
                observed_at=now.isoformat(),
            )
            ready = repository.save(ready, expected_checkpoint_version=0)
            changed_profile = build_embedding_profile(
                provider_alias="mock-s94", model_profile_id="Qwen3-Embedding-4B",
                model_revision="bf16-revision-2", deployment_id="mock-local",
                vector_dimension=2560,
            )
            reconciled = reconcile_vector_index(
                manifest=ready, source_snapshot=source,
                embedding_profile=changed_profile, payload_count=1,
                payload_fingerprint=ready["payload_fingerprint"],
                repository=repository, observed_at=now.isoformat(),
            )
            admitted = admit_vector_rebuild(
                manifest=reconciled["manifest"], source_snapshot=source,
                embedding_profile=changed_profile, repository=repository,
                trace_id="s94-rebuild-trace", request_id="s94-rebuild-request",
                observed_at=now.isoformat(),
            )
            old = repository.get(
                manifest["vector_index_id"], tenant_id="s94-adapter-tenant",
                owner_subject_id="s94-adapter-owner",
            )
            new = repository.get(
                admitted["manifest"]["vector_index_id"],
                tenant_id="s94-adapter-tenant", owner_subject_id="s94-adapter-owner",
            )
            checks.update({
                "drift_reason": reconciled["freshness"]["reason"] == "MODEL_REVISION_CHANGED",
                "old_rebuild_required": old is not None and old["status"] == "REBUILD_REQUIRED",
                "old_checkpoint": old is not None and old["checkpoint_version"] == 3,
                "replacement_action": admitted["action"] == "CREATE_REPLACEMENT",
                "replacement_identity": new is not None
                and new["vector_index_id"] != manifest["vector_index_id"],
                "replacement_building": new is not None and new["status"] == "BUILDING",
                "replacement_profile": new is not None
                and new["embedding_profile"]["model_revision"] == "bf16-revision-2",
            })
        finally:
            engine.dispose()
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM cx_content_objects WHERE content_object_id = %s", (ids.content,))
                cursor.execute("DELETE FROM cx_source_files WHERE source_file_id = %s", (ids.source,))
                cursor.execute("SELECT count(*) FROM cx_vector_indexes WHERE content_object_id = %s", (ids.content,))
                checks["cleanup_complete"] = cursor.fetchone() == (0,)
    return {
        "checks": checks,
        "failed_checks": [key for key, value in checks.items() if not value],
        "check_count": len(checks),
        "rebuild_strategy": "preserve_old_create_replacement",
    }


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    return unquote(parsed.username or "") == EXPECTED_ROLE and parsed.path.lstrip("/") == EXPECTED_DATABASE


def _failure(code: str, detail: Any) -> dict[str, Any]:
    return {"status": "FAIL", "smoke_schema_version": SCHEMA_VERSION,
            "error": {"code": code, "detail": detail}}


def _summary(result: Mapping[str, Any]) -> str:
    status = str(result["status"]).lower()
    if status == "skipped":
        return f"cx_vector_reconciliation_postgres_smoke=skipped reason={SMOKE_ENV}"
    if status == "pass":
        return ("cx_vector_reconciliation_postgres_smoke=pass "
                f"checks={result['check_count']}/{result['check_count']} "
                "strategy=preserve_old_create_replacement remote_required=False")
    return f"cx_vector_reconciliation_postgres_smoke=fail error={result['error']['code']}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_vector_reconciliation_postgres_smoke()
    print(_summary(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
