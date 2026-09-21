#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Callable, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import psycopg
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.pgvector_store import build_pgvector_cx_vector_store  # noqa: E402
from nex_cx.vector_index_freshness import (  # noqa: E402
    build_embedding_profile,
    build_source_snapshot,
    build_vector_index_manifest,
)
from nex_cx.vector_index_publish import publish_vector_index  # noqa: E402
from nex_cx.vector_index_repository import (  # noqa: E402
    SqlAlchemyVectorIndexRepository,
)
from nex_cx.vector_retrieval_guard import search_fresh_vector_index  # noqa: E402
from nex_mo.remote_provider import (  # noqa: E402
    OPENAI_EMBEDDINGS_SHAPE,
    build_remote_embedding_execution_config,
    execute_remote_embedding_request,
    expected_models_from_env,
)
from nex_runtime import (  # noqa: E402
    build_engine,
    build_session_factory,
    redact_database_url,
)
from run_cx_pgvector_adapter_postgres_smoke import (  # noqa: E402
    _digest,
    _seed_fixture,
)
from run_migrations import (  # noqa: E402
    run_service_migrations,
    service_database_env,
    service_database_url,
)
from run_protected_dgx_live_profile import (  # noqa: E402
    protected_dgx_vllm_profile_defaults,
)


SCHEMA_VERSION = "cx_vector_live_embedding_pgvector_smoke.v1"
SMOKE_ENV = "NEX_CX_VECTOR_LIVE_EMBEDDING_PGVECTOR_SMOKE"
PROFILE_ENV = "NEX_CX_VECTOR_LIVE_EMBEDDING_PGVECTOR_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"
VECTOR_DIMENSION = 2560
LIVE_INPUT = "NeX CX 벡터 저장소와 인덱스 freshness 통합 검증 문장입니다."

HttpRequester = Callable[..., Any]


def run_cx_vector_live_embedding_pgvector_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure("profile_not_allowed", f"{PROFILE_ENV} must be test.")

    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
    }
    issues = remote_embedding_configuration_issues(effective_env)
    if issues:
        return _failure("configuration_invalid", issues)

    database_url = ""
    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(
            SERVICE_ID,
            profile=profile,
            environ=effective_env,
        )
        if not _target_url_allowed(database_url):
            return _failure("target_not_allowed", "CX test database target is required.")
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_smoke(
            database_url,
            environ={**effective_env, database_env: database_url},
            database_env=database_env,
            requester=requester,
        )
        if execution["failed_checks"]:
            return _failure(
                "live_embedding_pgvector_smoke_failed",
                execution["failed_checks"],
                execution=execution,
            )
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            "migration": {
                "applied": list(migration.applied),
                "skipped": list(migration.skipped),
            },
            "remote_embedding_required": True,
            **execution,
        }
        assert_evidence_redacted(evidence, effective_env)
        return evidence
    except Exception as exc:  # pragma: no cover - protected live evidence
        return _failure(
            "execution_failed",
            exc.__class__.__name__,
            redacted_database_url=(
                redact_database_url(database_url) if database_url else None
            ),
        )


def remote_embedding_configuration_issues(
    environ: Mapping[str, str],
) -> list[dict[str, Any]]:
    env = dict(environ)
    try:
        config = build_remote_embedding_execution_config(env)
    except ValueError:
        return [{"error_code": "remote_embedding_timeout_invalid"}]

    issues: list[dict[str, Any]] = []
    if not config.configured:
        issues.append({"error_code": "remote_embedding_endpoint_not_configured"})
    if not config.api_key:
        issues.append({"error_code": "remote_embedding_authorization_not_configured"})
    if config.request_shape != OPENAI_EMBEDDINGS_SHAPE:
        issues.append(
            {
                "error_code": "remote_embedding_request_shape_mismatch",
                "observed": config.request_shape,
                "expected": OPENAI_EMBEDDINGS_SHAPE,
            }
        )
    expected_models = expected_models_from_env(
        env.get("NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS"),
        ("Qwen3-Embedding-4B",),
    )
    if config.model_name not in expected_models:
        issues.append(
            {
                "error_code": "remote_embedding_model_mismatch",
                "observed": config.model_name,
                "expected": list(expected_models),
            }
        )
    return issues


def request_live_embedding(
    environ: Mapping[str, str],
    *,
    requester: HttpRequester | None = None,
) -> tuple[tuple[float, ...], dict[str, Any]]:
    env = dict(environ)
    config = build_remote_embedding_execution_config(env)
    response = execute_remote_embedding_request(
        {"alias": "cx-vector-live-smoke", "inputs": [LIVE_INPUT]},
        environ=env,
        requester=requester,
    )
    data = response.get("data")
    if not isinstance(data, list) or len(data) != 1:
        raise ValueError("Remote embedding response must contain exactly one item.")
    item = data[0]
    raw_vector = item.get("embedding") if isinstance(item, dict) else None
    if not isinstance(raw_vector, list):
        raise ValueError("Remote embedding response vector is missing.")
    vector = tuple(float(value) for value in raw_vector)
    if len(vector) != VECTOR_DIMENSION:
        raise ValueError("Remote embedding vector dimension does not match S94.")
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("Remote embedding vector contains a non-finite value.")
    if not any(value != 0.0 for value in vector):
        raise ValueError("Remote embedding vector must not be all zero.")
    return vector, {
        "config": config.to_safe_summary(),
        "response_count": len(data),
        "vector_dimension": len(vector),
        "finite": True,
        "non_zero": True,
    }


def _execute_smoke(  # pragma: no cover - protected PostgreSQL/live evidence
    database_url: str,
    *,
    environ: Mapping[str, str],
    database_env: str,
    requester: HttpRequester | None = None,
) -> dict[str, Any]:
    vector, provider_evidence = request_live_embedding(
        environ,
        requester=requester,
    )
    config = build_remote_embedding_execution_config(dict(environ))
    ids = SimpleNamespace(
        source=uuid4(),
        content=uuid4(),
        upload=uuid4(),
        artifact=uuid4(),
        chunk_set=uuid4(),
        chunk=uuid4(),
    )
    now = datetime.now(UTC)
    source_hash = _digest(f"source:{ids.content}")
    markdown_hash = _digest(f"markdown:{ids.content}")
    source = build_source_snapshot(
        chunk_set_id=str(ids.chunk_set),
        chunk_policy_id="1000_100",
        source_markdown_sha256=markdown_hash,
        chunks=[
            {
                "chunk_id": str(ids.chunk),
                "ordinal": 0,
                "text_sha256": _digest(f"chunk:{ids.chunk}"),
            }
        ],
    )
    profile = build_embedding_profile(
        provider_alias="dgx-openai-compatible",
        model_profile_id=config.model_name,
        model_revision=config.model_revision,
        deployment_id=config.deployment_id,
        vector_dimension=VECTOR_DIMENSION,
    )
    manifest = build_vector_index_manifest(
        content_object_id=str(ids.content),
        tenant_ref={"type": "oa.tenant", "id": "s94-adapter-tenant"},
        owner_subject_ref={"type": "oa.user", "id": "s94-adapter-owner"},
        source_snapshot=source,
        embedding_profile=profile,
        trace_id="s94-adapter-trace",
        request_id="s94-adapter-request",
        observed_at=now.isoformat(),
    )
    checks: dict[str, bool] = {}
    engine = None
    with psycopg.connect(database_url, autocommit=True) as connection:
        try:
            _seed_fixture(
                connection,
                ids=ids,
                manifest=manifest,
                source_hash=source_hash,
                markdown_hash=markdown_hash,
                observed_at=now,
            )
            engine = build_engine(database_url)
            repository = SqlAlchemyVectorIndexRepository(build_session_factory(engine))
            vector_store = build_pgvector_cx_vector_store(
                database_env=database_env,
                environ=environ,
                workload="worker",
            )
            context = CxAccessContext(
                caller_service_id="nex-cx",
                tenant_id="s94-adapter-tenant",
                subject_id="s94-adapter-owner",
                request_id="s94-live-embedding-request",
                trace_id="93900000000000000000000000000001",
                scopes=("service:call",),
            )
            ready = publish_vector_index(
                access_context=context,
                manifest=manifest,
                vectors_by_chunk_id={str(ids.chunk): vector},
                vector_store=vector_store,
                repository=repository,
                observed_at=now.isoformat(),
            )
            retrieval = search_fresh_vector_index(
                access_context=context,
                vector_index_id=ready["vector_index_id"],
                source_snapshot=source,
                embedding_profile=profile,
                query_vector=vector,
                limit=1,
                repository=repository,
                vector_store=vector_store,
            )
            with engine.connect() as sql_connection:
                persisted = sql_connection.execute(
                    text(
                        """
                        SELECT status, provider_alias, model_profile_id,
                               model_revision, deployment_id, vector_dimension,
                               payload_count
                        FROM cx_vector_indexes
                        WHERE vector_index_id = :vector_index_id
                        """
                    ),
                    {"vector_index_id": ready["vector_index_id"]},
                ).mappings().one()
            matches = retrieval["matches"]
            checks.update(
                {
                    "remote_request_completed": provider_evidence["response_count"] == 1,
                    "remote_vector_dimension": provider_evidence["vector_dimension"]
                    == VECTOR_DIMENSION,
                    "remote_vector_finite": provider_evidence["finite"],
                    "remote_vector_non_zero": provider_evidence["non_zero"],
                    "provider_profile_persisted": (
                        persisted["provider_alias"] == "dgx-openai-compatible"
                        and persisted["model_profile_id"] == config.model_name
                        and persisted["model_revision"] == config.model_revision
                        and persisted["deployment_id"] == config.deployment_id
                        and persisted["vector_dimension"] == VECTOR_DIMENSION
                    ),
                    "atomic_publish_ready": persisted["status"] == "READY"
                    and persisted["payload_count"] == 1,
                    "fresh_retrieval_admitted": retrieval["freshness"][
                        "retrieval_usable"
                    ],
                    "pgvector_match_returned": len(matches) == 1
                    and matches[0]["chunk_id"] == str(ids.chunk),
                    "self_similarity": len(matches) == 1
                    and math.isclose(matches[0]["score"], 1.0, abs_tol=1e-6),
                    "primary_fallback_route": vector_store.uses_primary_database,
                }
            )
        finally:
            if engine is not None:
                engine.dispose()
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM cx_vectors WHERE vector_index_id = %s",
                    (manifest["vector_index_id"],),
                )
                cursor.execute(
                    "DELETE FROM cx_content_objects WHERE content_object_id = %s",
                    (ids.content,),
                )
                cursor.execute(
                    "DELETE FROM cx_source_files WHERE source_file_id = %s",
                    (ids.source,),
                )
                cursor.execute(
                    "SELECT count(*) FROM cx_vector_indexes WHERE vector_index_id = %s",
                    (manifest["vector_index_id"],),
                )
                checks["cleanup_complete"] = cursor.fetchone() == (0,)
    return {
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "check_count": len(checks),
        "provider": provider_evidence,
        "publish_protocol": "remote_embed_validate_publish_cas_retrieve",
    }


def assert_evidence_redacted(
    evidence: object,
    environ: Mapping[str, str],
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    protected_values = (
        environ.get("NEX_MO_REMOTE_EMBEDDING_URL", ""),
        environ.get("NEX_MO_REMOTE_EMBEDDING_API_KEY", ""),
        LIVE_INPUT,
    )
    if any(value and value in serialized for value in protected_values):
        raise ValueError("Live embedding pgvector evidence is not redacted.")


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    return (
        unquote(parsed.username or "") == EXPECTED_ROLE
        and parsed.path.lstrip("/") == EXPECTED_DATABASE
    )


def _failure(code: str, detail: Any, **extra: Any) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "error": {"code": code, "detail": detail},
        **extra,
    }


def _summary(result: Mapping[str, Any]) -> str:
    status = str(result["status"]).lower()
    if status == "skipped":
        return f"cx_vector_live_embedding_pgvector_smoke=skipped reason={SMOKE_ENV}"
    if status == "pass":
        return (
            "cx_vector_live_embedding_pgvector_smoke=pass "
            f"checks={result['check_count']}/{result['check_count']} "
            f"dimension={result['provider']['vector_dimension']} "
            "provider=openai_compatible database=nex_cx_test"
        )
    return (
        "cx_vector_live_embedding_pgvector_smoke=fail "
        f"error={result['error']['code']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_vector_live_embedding_pgvector_smoke()
    print(_summary(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
