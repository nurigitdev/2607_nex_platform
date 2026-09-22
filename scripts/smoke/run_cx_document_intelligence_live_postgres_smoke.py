#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from fastapi.testclient import TestClient
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

from nex_cx.document_intelligence_observability import (  # noqa: E402
    CX_DOCUMENT_INTELLIGENCE_READY_EVENT,
    CX_DOCUMENT_INTELLIGENCE_SIMILARITY_EVENT,
)
from nex_cx.document_intelligence_orchestration import (  # noqa: E402
    register_document_intelligence_routes,
)
from nex_cx.embedding_index import DEFAULT_EMBEDDING_ALIAS  # noqa: E402
from nex_cx.ingestion import (  # noqa: E402
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    run_text_extraction_job,
)
from nex_cx.private_text_store import FileSystemCxPrivateTextStore  # noqa: E402
from nex_cx.repository import SqlAlchemyCxContentRepository  # noqa: E402
from nex_cx.summary_pgvector_store import SummaryPgVectorStore  # noqa: E402
from nex_cx.summary_similarity import PostgresSummarySimilarityStore  # noqa: E402
from nex_mo.providers import register_mock_provider_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from run_cx_document_library_postgres_smoke import _migration_evidence  # noqa: E402
from run_cx_real_document_processing_pipeline_postgres_smoke import (  # noqa: E402
    _delete_real_document_processing_rows,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)
from run_protected_dgx_live_profile import (  # noqa: E402
    protected_dgx_vllm_profile_defaults,
)
from run_protected_live_rag_postgres_smoke import (  # noqa: E402
    LiveRagSmokeStageError,
    _run_stage,
)
from run_protected_live_rag_smoke import (  # noqa: E402
    HttpRequester,
    InProcessLiveMoClient,
    patched_environ,
    patched_remote_request,
)


SCHEMA_VERSION = "cx_document_intelligence_live_postgres_smoke.v1"
SMOKE_ENV = "NEX_CX_DOCUMENT_INTELLIGENCE_LIVE_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_CX_DOCUMENT_INTELLIGENCE_LIVE_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"
EXPECTED_EMBEDDING_MODEL = "Qwen3-Embedding-4B"
EXPECTED_GENERATION_MODEL = "Qwen3.5-4B"
EXPECTED_VECTOR_DIMENSION = 2560
TENANT_ID = "s96-live-tenant"
OWNER_ID = "s96-live-owner"
TRACE_ID = "95900000000000000000000000000001"
REQUEST_ID = "request-0959-live"
FORBIDDEN_SOURCE_MARKERS = (
    "S96_PRIVATE_SUMMARY_SOURCE_ALPHA",
    "S96_PRIVATE_SUMMARY_SOURCE_BETA",
)
PROTECTED_ENV_KEYS = (
    "NEX_CX_TEST_DATABASE_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_VLLM_API_KEY",
)
EXECUTION_STAGES = (
    "database_identity",
    "service_runtime",
    "document_alpha",
    "document_beta",
    "similarity",
    "provider_telemetry",
    "database_observation",
    "operational_events",
    "checks",
    "redaction",
    "cleanup",
)

SmokeExecutor = Callable[..., dict[str, Any]]


def run_cx_document_intelligence_live_postgres_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
    executor: SmokeExecutor | None = None,
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
        return _failure(
            "profile_not_allowed",
            f"{PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
        )

    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
    }
    missing = _missing_configuration(effective_env)
    if missing:
        return _failure(
            "configuration_invalid",
            "Required protected live configuration is missing.",
            profile=profile,
            diagnostics={"missing_env": missing},
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(
            SERVICE_ID,
            profile=profile,
            environ=effective_env,
        )
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execute = executor or _execute_live_smoke
        execution = execute(
            database_url=database_url,
            database_env=database_env,
            runtime_environ={
                **effective_env,
                SERVICE_SPECS[SERVICE_ID].database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
            requester=requester,
        )
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            "migration": _migration_evidence(migration),
            **execution,
        }
        assert_evidence_redacted(evidence, effective_env)
        return evidence
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)
    except LiveRagSmokeStageError as exc:
        failure = _failure(
            "execution_failed",
            exc.error_code,
            profile=profile,
            diagnostics=exc.to_safe_diagnostics(),
        )
        assert_evidence_redacted(failure, effective_env)
        return failure
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__, profile=profile)


def _missing_configuration(env: Mapping[str, str]) -> list[str]:
    required = (
        "NEX_CX_TEST_DATABASE_URL",
        "NEX_MO_REMOTE_EMBEDDING_URL",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY",
        "NEX_MO_VLLM_API_KEY",
    )
    missing = [key for key in required if not str(env.get(key, "")).strip()]
    if not (
        str(env.get("NEX_MO_VLLM_CHAT_COMPLETIONS_URL", "")).strip()
        or str(env.get("NEX_MO_VLLM_BASE_URL", "")).strip()
    ):
        missing.append("NEX_MO_VLLM_CHAT_COMPLETIONS_URL|NEX_MO_VLLM_BASE_URL")
    return missing


def _execute_live_smoke(  # pragma: no cover - protected PostgreSQL/DGX evidence
    *,
    database_url: str,
    database_env: str,
    runtime_environ: dict[str, str],
    requester: HttpRequester | None,
) -> dict[str, Any]:
    del database_env
    stage_status = {stage: "NOT_RUN" for stage in EXECUTION_STAGES}
    engine = build_engine(database_url)
    factory = build_session_factory(engine)
    documents: list[dict[str, str]] = []
    result: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="nex-cx-s96-live-") as temp_dir:
        root = Path(temp_dir)
        storage_config = _storage_config(root)
        repository = SqlAlchemyCxContentRepository(
            factory,
            local_source_root=storage_config.source_root,
        )
        store = ContentIngestionStore(
            content_repository=repository,
            private_summary_text_store=FileSystemCxPrivateTextStore(
                root / "private-summary"
            ),
        )
        vector_store = SummaryPgVectorStore(
            factory,
            redacted_database_url=redact_database_url(database_url),
            uses_primary_database=True,
        )
        similarity_store = PostgresSummarySimilarityStore(factory)
        events = InMemoryOperationalEventStore()
        mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
        register_mock_provider_routes(mo_app)
        mo_test_client = TestClient(mo_app)
        mo_client = InProcessLiveMoClient(mo_test_client)
        cx_app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        register_document_intelligence_routes(
            cx_app,
            store=store,
            generation_client=mo_client,
            embedding_client=mo_client,
            embedding_alias=DEFAULT_EMBEDDING_ALIAS,
            summary_vector_store=vector_store,
            summary_similarity_store=similarity_store,
            event_emitter=OperationalEventEmitter(service_id=SERVICE_ID, store=events),
        )
        cx_client = TestClient(cx_app)

        try:
            identity = _run_stage(
                "database_identity",
                stage_status,
                lambda: _read_database_identity(engine),
            )
            if identity != {"database": EXPECTED_DATABASE, "role": EXPECTED_ROLE}:
                raise LiveRagSmokeStageError(
                    stage="database_identity",
                    error_code="cx_document_intelligence_database_identity_mismatch",
                    detail="Protected smoke is not connected to the expected CX test database.",
                    stage_status=stage_status,
                )
            stage_status["service_runtime"] = "PASS"
            with patched_environ(runtime_environ):
                with patched_remote_request(requester):
                    import nex_mo.remote_provider as remote_provider

                    remote_provider.reset_remote_provider_telemetry()
                    alpha = _run_stage(
                        "document_alpha",
                        stage_status,
                        lambda: _create_and_run_document(
                            store=store,
                            storage_config=storage_config,
                            client=cx_client,
                            marker=FORBIDDEN_SOURCE_MARKERS[0],
                            filename="s96-alpha.md",
                            request_id=f"{REQUEST_ID}-alpha",
                        ),
                    )
                    documents.append(alpha["lineage"])
                    beta = _run_stage(
                        "document_beta",
                        stage_status,
                        lambda: _create_and_run_document(
                            store=store,
                            storage_config=storage_config,
                            client=cx_client,
                            marker=FORBIDDEN_SOURCE_MARKERS[1],
                            filename="s96-beta.md",
                            request_id=f"{REQUEST_ID}-beta",
                        ),
                    )
                    documents.append(beta["lineage"])
                    similarity = _run_stage(
                        "similarity",
                        stage_status,
                        lambda: _post_similarity(
                            cx_client,
                            document_id=alpha["lineage"]["document_id"],
                            request_id=f"{REQUEST_ID}-similarity",
                        ),
                    )
                    telemetry = _run_stage(
                        "provider_telemetry",
                        stage_status,
                        lambda: _provider_telemetry(mo_test_client),
                    )
            db_observation = _run_stage(
                "database_observation",
                stage_status,
                lambda: _read_database_observation(
                    engine,
                    [item["document_id"] for item in documents],
                ),
            )
            event_observation = _run_stage(
                "operational_events",
                stage_status,
                lambda: {
                    "ready_count": len(
                        events.list_events(
                            event_type=CX_DOCUMENT_INTELLIGENCE_READY_EVENT
                        )
                    ),
                    "similarity_count": len(
                        events.list_events(
                            event_type=CX_DOCUMENT_INTELLIGENCE_SIMILARITY_EVENT
                        )
                    ),
                },
            )
            checks = _run_stage(
                "checks",
                stage_status,
                lambda: _checks(
                    alpha=alpha,
                    beta=beta,
                    similarity=similarity,
                    telemetry=telemetry,
                    database_identity=identity,
                    db_observation=db_observation,
                    event_observation=event_observation,
                ),
            )
            if not all(checks.values()):
                raise LiveRagSmokeStageError(
                    stage="checks",
                    error_code="cx_document_intelligence_live_checks_failed",
                    detail="Protected document-intelligence live checks failed.",
                    stage_status=stage_status,
                )
            result = {
                "stage_status": stage_status,
                "database_identity": identity,
                "provider_observation": _safe_provider_observation(telemetry),
                "document_observation": {
                    "ready_count": 2,
                    "summary_char_counts": [
                        alpha["safe"]["summary_char_count"],
                        beta["safe"]["summary_char_count"],
                    ],
                    "vector_dimensions": [
                        alpha["safe"]["vector_dimension"],
                        beta["safe"]["vector_dimension"],
                    ],
                },
                "similarity_observation": {
                    "candidate_count": similarity["result"]["candidate_count"],
                    "source_excluded": similarity["result"][
                        "excluded_content_object_id"
                    ]
                    == alpha["lineage"]["document_id"],
                },
                "database_observation": db_observation,
                "event_observation": event_observation,
                "checks": checks,
            }
            _run_stage(
                "redaction",
                stage_status,
                lambda: assert_evidence_redacted(result, runtime_environ),
            )
        finally:
            cleanup = _run_stage(
                "cleanup",
                stage_status,
                lambda: _cleanup(engine, documents),
            )
            result["cleanup_observation"] = cleanup
            engine.dispose()
    return result


def _storage_config(root: Path) -> CxStorageConfig:  # pragma: no cover
    return CxStorageConfig(
        data_root=root,
        source_root=root / "source",
        extracted_markdown_root=root / "markdown",
        extraction_temp_root=root / "temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def _create_and_run_document(  # pragma: no cover - protected evidence
    *,
    store: ContentIngestionStore,
    storage_config: CxStorageConfig,
    client: TestClient,
    marker: str,
    filename: str,
    request_id: str,
) -> dict[str, Any]:
    source_text = (
        f"# {marker}\n\n"
        "The platform document intelligence flow stores a bounded summary, "
        "publishes one owner-private embedding, and supports similarity search."
    )
    record = build_upload_registration(
        {
            "filename": filename,
            "content_type": "text/markdown",
            "content_text": source_text,
            "tenant_ref": {"type": "oa.tenant", "id": TENANT_ID},
            "owner_subject_ref": {"type": "oa.user", "id": OWNER_ID},
        },
        storage_config=storage_config,
        request_id=request_id,
        trace_id=TRACE_ID,
    )
    store.save_upload_registration(record, source_text=source_text)
    run_text_extraction_job(
        record["extraction"]["job_id"],
        store=store,
        storage_config=storage_config,
        request_id=request_id,
        trace_id=TRACE_ID,
    )
    refs = store.get_content_ref(record["document_id"])
    if refs is None:
        raise RuntimeError("Document persistence lineage was not created")
    response = client.post(
        f"/api/v1/documents/{record['document_id']}/intelligence/run",
        headers=_headers(request_id),
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "lineage": {
            "document_id": str(record["document_id"]),
            "source_file_id": str(refs["source_file_id"]),
        },
        "safe": {
            "status": payload["status"],
            "summary_char_count": payload["summary"]["summary_char_count"],
            "generation_model": payload["summary"]["summarizer"]["model_revision"],
            "embedding_model": payload["summary_embedding"]["model_revision"],
            "vector_dimension": payload["summary_embedding"]["vector_dimension"],
            "fresh": payload["summary_vector"]["freshness"]["usable"],
            "raw_summary_included": payload["raw_summary_included"],
            "raw_vector_included": payload["raw_vector_included"],
        },
    }


def _post_similarity(  # pragma: no cover - protected evidence
    client: TestClient,
    *,
    document_id: str,
    request_id: str,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/documents/{document_id}/intelligence/similar",
        headers=_headers(request_id),
        json={"limit": 5, "minimum_score": -1.0},
    )
    response.raise_for_status()
    return response.json()


def _headers(request_id: str) -> dict[str, str]:  # pragma: no cover
    token = issue_mock_service_token(
        service_id="nex-ae-api",
        audience=SERVICE_ID,
    ).access_token
    return {
        "Authorization": f"Bearer {token}",
        "X-NEX-Tenant-ID": TENANT_ID,
        "X-NEX-Subject-ID": OWNER_ID,
        "X-Request-ID": request_id,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _provider_telemetry(client: TestClient) -> dict[str, Any]:  # pragma: no cover
    token = issue_mock_service_token(
        service_id=SERVICE_ID,
        audience="nex-mo",
    ).access_token
    response = client.get(
        "/api/v1/provider-telemetry",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Service-ID": SERVICE_ID,
            "X-Request-ID": REQUEST_ID,
            "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
        },
    )
    response.raise_for_status()
    return response.json()


def _safe_provider_observation(telemetry: Mapping[str, Any]) -> dict[str, Any]:
    by_capability = {
        item["capability"]: item
        for item in telemetry.get("data", [])
        if isinstance(item, dict) and isinstance(item.get("capability"), str)
    }
    return {
        capability: {
            "success_count": int(
                by_capability.get(capability, {}).get("success_count", 0)
            ),
            "failure_count": int(
                by_capability.get(capability, {}).get("failure_count", 0)
            ),
        }
        for capability in ("generation", "embedding")
    }


def _read_database_identity(engine: Any) -> dict[str, str]:  # pragma: no cover
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT current_database() AS database, current_user AS role")
        ).mappings().one()
    return {"database": str(row["database"]), "role": str(row["role"])}


def _read_database_observation(  # pragma: no cover - protected evidence
    engine: Any,
    document_ids: list[str],
) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    count(DISTINCT content.content_object_id) AS content_count,
                    count(DISTINCT summary.document_summary_id) AS summary_count,
                    count(DISTINCT embedding.summary_embedding_id) AS embedding_count,
                    count(DISTINCT vector.summary_vector_id) AS vector_count,
                    min(embedding.vector_dimension) AS min_dimension,
                    max(embedding.vector_dimension) AS max_dimension,
                    min(embedding.model_revision) AS min_model,
                    max(embedding.model_revision) AS max_model
                FROM cx_content_objects AS content
                JOIN cx_document_summaries AS summary
                  ON summary.content_object_id = content.content_object_id
                JOIN cx_document_summary_embeddings AS embedding
                  ON embedding.document_summary_id = summary.document_summary_id
                JOIN cx_summary_vectors AS vector
                  ON vector.summary_embedding_id = embedding.summary_embedding_id
                WHERE content.content_object_id IN (:alpha, :beta)
                  AND content.tenant_ref_id = :tenant_id
                  AND content.owner_subject_ref_id = :owner_id
                """
            ),
            {
                "alpha": document_ids[0],
                "beta": document_ids[1],
                "tenant_id": TENANT_ID,
                "owner_id": OWNER_ID,
            },
        ).mappings().one()
    return {
        "content_count": int(row["content_count"]),
        "summary_count": int(row["summary_count"]),
        "embedding_count": int(row["embedding_count"]),
        "vector_count": int(row["vector_count"]),
        "min_dimension": int(row["min_dimension"] or 0),
        "max_dimension": int(row["max_dimension"] or 0),
        "min_model": row["min_model"],
        "max_model": row["max_model"],
    }


def _checks(  # pragma: no cover - protected evidence
    *,
    alpha: dict[str, Any],
    beta: dict[str, Any],
    similarity: dict[str, Any],
    telemetry: dict[str, Any],
    database_identity: dict[str, str],
    db_observation: dict[str, Any],
    event_observation: dict[str, int],
) -> dict[str, bool]:
    documents = (alpha["safe"], beta["safe"])
    provider = _safe_provider_observation(telemetry)
    candidates = similarity["result"]["candidates"]
    return {
        "test_database_connected": database_identity
        == {"database": EXPECTED_DATABASE, "role": EXPECTED_ROLE},
        "two_documents_ready": all(item["status"] == "READY" for item in documents),
        "summary_bounded": all(
            0 < item["summary_char_count"] < 1000 for item in documents
        ),
        "generation_model_current": all(
            item["generation_model"] == EXPECTED_GENERATION_MODEL for item in documents
        ),
        "embedding_model_current": all(
            item["embedding_model"] == EXPECTED_EMBEDDING_MODEL for item in documents
        ),
        "embedding_dimension_current": all(
            item["vector_dimension"] == EXPECTED_VECTOR_DIMENSION for item in documents
        ),
        "vectors_fresh": all(item["fresh"] is True for item in documents),
        "private_payloads_absent": all(
            item["raw_summary_included"] is False
            and item["raw_vector_included"] is False
            for item in documents
        ),
        "similar_candidate_found": similarity["result"]["candidate_count"] >= 1,
        "source_document_excluded": all(
            candidate["content_object_id"] != alpha["lineage"]["document_id"]
            for candidate in candidates
        ),
        "postgres_lineage_persisted": db_observation["content_count"] == 2
        and db_observation["summary_count"] == 2
        and db_observation["embedding_count"] == 2
        and db_observation["vector_count"] == 2,
        "postgres_embedding_lineage_current": db_observation["min_dimension"]
        == db_observation["max_dimension"]
        == EXPECTED_VECTOR_DIMENSION
        and db_observation["min_model"]
        == db_observation["max_model"]
        == EXPECTED_EMBEDDING_MODEL,
        "generation_live_calls_observed": provider["generation"]["success_count"] >= 2,
        "embedding_live_calls_observed": provider["embedding"]["success_count"] >= 2,
        "metadata_events_observed": event_observation
        == {"ready_count": 2, "similarity_count": 1},
    }


def _cleanup(  # pragma: no cover - protected evidence
    engine: Any,
    documents: list[dict[str, str]],
) -> dict[str, Any]:
    observations = []
    for item in reversed(documents):
        observations.append(
            _delete_real_document_processing_rows(
                engine,
                document_id=item["document_id"],
                source_file_id=item["source_file_id"],
                pipeline_run_id=None,
                job_id=None,
            )
        )
    complete = all(
        all(value == 0 for value in observation["after"].values())
        for observation in observations
    )
    return {"document_count": len(observations), "complete": complete}


def assert_evidence_redacted(
    evidence: Mapping[str, Any],
    environ: Mapping[str, str],
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)
    for marker in FORBIDDEN_SOURCE_MARKERS:
        if marker in serialized:
            raise ValueError("Document-intelligence evidence contains private source text.")
    for key in PROTECTED_ENV_KEYS:
        secret = _secret_fragment(key, environ.get(key))
        if secret and len(secret) >= 4 and secret in serialized:
            raise ValueError(
                "Document-intelligence evidence contains an unredacted protected value."
            )
    if "/nex-cx-s96-live-" in serialized or "private-summary" in serialized:
        raise ValueError("Document-intelligence evidence contains a local storage path.")


def _secret_fragment(key: str, value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if key.endswith("DATABASE_URL"):
        authority = value.split("@", 1)[0]
        if "://" in authority:
            authority = authority.split("://", 1)[1]
        return authority.rsplit(":", 1)[1] if ":" in authority else None
    if key.endswith("API_KEY"):
        return value
    return None


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }
    if diagnostics is not None:
        result["diagnostics"] = diagnostics
    return result


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status", "FAIL"))
    if status == "SKIPPED":
        return f"cx_document_intelligence_live_postgres=skipped reason={SMOKE_ENV}"
    if status == "PASS":
        document = evidence["document_observation"]
        similarity = evidence["similarity_observation"]
        return (
            "cx_document_intelligence_live_postgres=pass "
            f"db={evidence['database_identity']['database']} "
            f"ready={document['ready_count']} "
            f"vector_dim={max(document['vector_dimensions'])} "
            f"candidates={similarity['candidate_count']}"
        )
    diagnostics = evidence.get("diagnostics", {})
    stage = (
        diagnostics.get("stage", "unknown")
        if isinstance(diagnostics, dict)
        else "unknown"
    )
    return (
        "cx_document_intelligence_live_postgres=fail "
        f"reason={evidence.get('failure_code', 'unknown')} stage={stage}"
    )


def main(argv: list[str] | None = None) -> int:
    load_env_file(ROOT / ".env")
    parser = argparse.ArgumentParser(
        description="Run protected CX document-intelligence PostgreSQL/DGX evidence."
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    evidence = run_cx_document_intelligence_live_postgres_smoke()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
