#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Mapping
from copy import deepcopy
import hashlib
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

import nex_mo.remote_provider as remote_provider  # noqa: E402
from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.generation import (  # noqa: E402
    GenerationExecutionStore,
    register_generation_routes,
)
from nex_cx.generation_observability import (  # noqa: E402
    CX_GENERATION_COMPLETED_EVENT,
    CX_GENERATION_REPLAYED_EVENT,
)
from nex_cx.generation_private_output import (  # noqa: E402
    GENERATION_OUTPUT_PAYLOAD_KIND,
)
from nex_cx.generation_read_model import GenerationReadModel  # noqa: E402
from nex_cx.generation_repository import (  # noqa: E402
    SqlAlchemyGenerationRuntimeRepository,
)
from nex_cx.generation_runtime import (  # noqa: E402
    GroundedGenerationRuntime,
    SqlAlchemyGenerationAdmissionRepository,
    generation_idempotency_key_hash,
)
from nex_cx.private_content import build_private_payload_key  # noqa: E402
from nex_cx.private_text_store import FileSystemCxPrivateTextStore  # noqa: E402
from nex_mo.providers import register_mock_provider_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    OperationalEventEmitter,
    SERVICE_SPECS,
    SqlAlchemyOperationalEventStore,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from run_cx_document_library_postgres_smoke import _migration_evidence  # noqa: E402
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
    read_provider_telemetry,
)


SCHEMA_VERSION = "cx_grounded_generation_live_postgres_smoke.v1"
SMOKE_ENV = "NEX_CX_GROUNDED_GENERATION_LIVE_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_CX_GROUNDED_GENERATION_LIVE_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"
EXPECTED_GENERATION_MODEL = "Qwen3.5-4B"
TENANT_ID = "s97-live-tenant"
OWNER_ID = "s97-live-owner"
OTHER_OWNER_ID = "s97-live-other-owner"
TRACE_ID = "96900000000000000000000000000001"
REQUEST_ID = "request-0969-live"
IDEMPOTENCY_KEY = "s97-grounded-generation-live"
RETRIEVAL_PACKAGE_ID = "96900000-0000-4000-8000-000000000001"
RETRIEVAL_PACKAGE_HASH = "9" * 64
EVIDENCE_ID = "evidence-s97-live-001"
PRIVATE_EVIDENCE_MARKER = "S97_PRIVATE_GROUNDED_EVIDENCE"
PRIVATE_PROMPT_MARKER = "S97_PRIVATE_GROUNDED_PROMPT"
PROTECTED_ENV_KEYS = (
    "NEX_CX_TEST_DATABASE_URL",
    "NEX_MO_VLLM_API_KEY",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
)
EXECUTION_STAGES = (
    "database_identity",
    "retrieval_package_seed",
    "service_runtime",
    "generation",
    "restart_replay",
    "restart_reads",
    "owner_isolation",
    "provider_telemetry",
    "database_observation",
    "operational_events",
    "checks",
    "redaction",
    "cleanup",
)

SmokeExecutor = Callable[..., dict[str, Any]]


class StaticRetrievalPackageStore:
    def __init__(self, package: Mapping[str, Any]) -> None:
        self._package = deepcopy(dict(package))

    def get_retrieval_package(
        self,
        retrieval_package_id: str,
    ) -> dict[str, Any] | None:
        if retrieval_package_id != self._package["retrieval_package_id"]:
            return None
        return deepcopy(self._package)


def run_cx_grounded_generation_live_postgres_smoke(
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
    if effective_env.get("NEX_MO_VLLM_MODEL") != EXPECTED_GENERATION_MODEL:
        return _failure(
            "generation_model_mismatch",
            "Protected live generation model does not match the frozen S97 model.",
            profile=profile,
            diagnostics={
                "expected_model": EXPECTED_GENERATION_MODEL,
                "configured_model": effective_env.get("NEX_MO_VLLM_MODEL"),
            },
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
            "generation_model": EXPECTED_GENERATION_MODEL,
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
    required = ("NEX_CX_TEST_DATABASE_URL", "NEX_MO_VLLM_API_KEY")
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
    generation_id: str | None = None
    result: dict[str, Any] = {}
    access_context = _smoke_access_context()
    with tempfile.TemporaryDirectory(prefix="nex-cx-s97-live-") as temp_dir:
        private_store = FileSystemCxPrivateTextStore(Path(temp_dir) / "generated")
        package_store = StaticRetrievalPackageStore(_retrieval_package())
        execution_repository = SqlAlchemyGenerationRuntimeRepository(
            factory,
            source_kind="postgres-write",
            database_env="NEX_CX_TEST_DATABASE_URL",
            redacted_database_url=redact_database_url(database_url),
        )
        admission_repository = SqlAlchemyGenerationAdmissionRepository(factory)
        event_store = SqlAlchemyOperationalEventStore(factory)
        event_emitter = OperationalEventEmitter(
            service_id=SERVICE_ID,
            store=event_store,
        )
        mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
        register_mock_provider_routes(mo_app)
        mo_test_client = TestClient(mo_app)
        mo_client = InProcessLiveMoClient(mo_test_client)

        try:
            identity = _run_stage(
                "database_identity",
                stage_status,
                lambda: _read_database_identity(engine),
            )
            if identity != {"database": EXPECTED_DATABASE, "role": EXPECTED_ROLE}:
                raise LiveRagSmokeStageError(
                    stage="database_identity",
                    error_code="cx_grounded_generation_database_identity_mismatch",
                    detail="Protected smoke is not connected to the expected CX test database.",
                    stage_status=stage_status,
                )

            _run_stage(
                "retrieval_package_seed",
                stage_status,
                lambda: _seed_retrieval_package(engine),
            )

            first_client = _build_cx_client(
                admission_repository=admission_repository,
                execution_repository=execution_repository,
                private_store=private_store,
                package_store=package_store,
                mo_client=mo_client,
                event_emitter=event_emitter,
            )
            stage_status["service_runtime"] = "PASS"
            with patched_environ(runtime_environ):
                with patched_remote_request(requester):
                    remote_provider.reset_remote_provider_telemetry()
                    generation = _run_stage(
                        "generation",
                        stage_status,
                        lambda: _post_generation(first_client),
                    )
                    generation_id = str(generation["cx_generation_id"])

                    restarted_client = _build_cx_client(
                        admission_repository=SqlAlchemyGenerationAdmissionRepository(
                            factory
                        ),
                        execution_repository=SqlAlchemyGenerationRuntimeRepository(
                            factory,
                            source_kind="postgres-read",
                            database_env="NEX_CX_TEST_DATABASE_URL",
                            redacted_database_url=redact_database_url(database_url),
                        ),
                        private_store=FileSystemCxPrivateTextStore(private_store.root),
                        package_store=package_store,
                        mo_client=mo_client,
                        event_emitter=event_emitter,
                    )
                    replay = _run_stage(
                        "restart_replay",
                        stage_status,
                        lambda: _post_generation(restarted_client),
                    )
                    reads = _run_stage(
                        "restart_reads",
                        stage_status,
                        lambda: _read_generation(restarted_client, generation_id),
                    )
                    owner_isolation = _run_stage(
                        "owner_isolation",
                        stage_status,
                        lambda: _read_other_owner(restarted_client, generation_id),
                    )
                    telemetry = _run_stage(
                        "provider_telemetry",
                        stage_status,
                        lambda: read_provider_telemetry(
                            mo_test_client,
                            TRACE_ID,
                            REQUEST_ID,
                        ),
                    )

            database_observation = _run_stage(
                "database_observation",
                stage_status,
                lambda: _read_database_observation(engine, generation_id),
            )
            event_observation = _run_stage(
                "operational_events",
                stage_status,
                lambda: _read_event_observation(event_store, generation_id),
            )
            provider_observation = _safe_provider_observation(telemetry)
            generation_observation = _safe_generation_observation(
                generation,
                replay,
                reads,
                mo_client.last_generation_response,
            )
            checks = _run_stage(
                "checks",
                stage_status,
                lambda: _checks(
                    identity=identity,
                    generation=generation_observation,
                    owner_isolation=owner_isolation,
                    provider=provider_observation,
                    database=database_observation,
                    events=event_observation,
                ),
            )
            if not all(checks.values()):
                stage_status["checks"] = "FAIL"
                raise LiveRagSmokeStageError(
                    stage="checks",
                    error_code="cx_grounded_generation_live_checks_failed",
                    detail="Protected grounded generation live checks failed.",
                    stage_status=stage_status,
                )
            result = {
                "stage_status": stage_status,
                "database_identity": identity,
                "generation_observation": generation_observation,
                "owner_isolation_observation": owner_isolation,
                "provider_observation": provider_observation,
                "database_observation": database_observation,
                "event_observation": event_observation,
                "checks": checks,
            }
            _run_stage(
                "redaction",
                stage_status,
                lambda: assert_evidence_redacted(result, runtime_environ),
            )
        finally:
            result["cleanup_observation"] = _run_stage(
                "cleanup",
                stage_status,
                lambda: _cleanup(
                    engine=engine,
                    private_store=private_store,
                    access_context=access_context,
                    generation_id=generation_id,
                ),
            )
            engine.dispose()
    return result


def _build_cx_client(  # pragma: no cover - protected evidence
    *,
    admission_repository: SqlAlchemyGenerationAdmissionRepository,
    execution_repository: SqlAlchemyGenerationRuntimeRepository,
    private_store: FileSystemCxPrivateTextStore,
    package_store: StaticRetrievalPackageStore,
    mo_client: InProcessLiveMoClient,
    event_emitter: OperationalEventEmitter,
) -> TestClient:
    runtime = GroundedGenerationRuntime(
        admission_repository=admission_repository,
        execution_repository=execution_repository,
        private_output_store=private_store,
    )
    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    register_generation_routes(
        app,
        store=GenerationExecutionStore(),
        mo_client=mo_client,
        retrieval_store=package_store,
        execution_runtime=runtime,
        read_model=GenerationReadModel(execution_repository, private_store),
        event_emitter=event_emitter,
    )
    return TestClient(app)


def _retrieval_package() -> dict[str, Any]:
    return {
        "retrieval_package_id": RETRIEVAL_PACKAGE_ID,
        "tenant_ref_type": "oa.tenant",
        "tenant_ref_id": TENANT_ID,
        "owner_subject_ref_type": "oa.user",
        "owner_subject_ref_id": OWNER_ID,
        "package_hash": RETRIEVAL_PACKAGE_HASH,
        "status": "READY",
        "query_text": PRIVATE_PROMPT_MARKER,
        "evidence_items": [
            {
                "evidence_id": EVIDENCE_ID,
                "citation_label": "[1]",
                "text": (
                    f"{PRIVATE_EVIDENCE_MARKER}: the verification phrase is "
                    "ALPHA NINETY SEVEN."
                ),
                "scores": {"final_score": 0.99},
            }
        ],
        "score_summary": {
            "best_score": 0.99,
            "confidence_bucket": "READY",
            "low_confidence_threshold": 0.2,
            "ranker_mix": "weighted_rrf_vector_bm25_with_rerank",
            "rerank_state": "APPLIED",
            "quality_policy_id": "retrieval_quality_v1",
        },
        "retrieval_profile": {
            "confidence_policy": {"low_confidence_threshold": 0.2}
        },
        "source_summary": {
            "source_count": 1,
            "document_count": 1,
            "chunk_count": 1,
        },
        "warnings": [],
    }


def _generation_payload() -> dict[str, Any]:
    return {
        "trace_id": TRACE_ID,
        "messages": [
            {
                "role": "user",
                "content": (
                    f"{PRIVATE_PROMPT_MARKER}: state only the verification phrase "
                    "from the evidence and include citation [1]."
                ),
            }
        ],
        "execution_mode": "GROUNDED_ANSWER",
        "template_id": "none",
        "prompt_binding_id": "ae.grounded_chat.default",
        "output_contract_id": "text_answer_v1",
        "provider_capability": "generation",
        "generation_profile": "grounded-answer",
        "retrieval_package_ref": {
            "retrieval_package_id": RETRIEVAL_PACKAGE_ID,
            "package_hash": RETRIEVAL_PACKAGE_HASH,
        },
        "selected_evidence_ids": [EVIDENCE_ID],
        "reasoning_mode": "disabled",
        "max_output_tokens": 128,
        "temperature": 0.0,
    }


def _post_generation(client: TestClient) -> dict[str, Any]:  # pragma: no cover
    response = client.post(
        "/api/v1/generations",
        json=_generation_payload(),
        headers=_headers(OWNER_ID, idempotency_key=IDEMPOTENCY_KEY),
    )
    response.raise_for_status()
    return response.json()


def _read_generation(  # pragma: no cover
    client: TestClient,
    generation_id: str,
) -> dict[str, Any]:
    headers = _headers(OWNER_ID)
    metadata_response = client.get(
        f"/api/v1/generations/{generation_id}",
        headers=headers,
    )
    metadata_response.raise_for_status()
    content_response = client.get(
        f"/api/v1/generations/{generation_id}/content",
        headers=headers,
    )
    content_response.raise_for_status()
    return {
        "metadata": metadata_response.json(),
        "content": content_response.json(),
    }


def _read_other_owner(  # pragma: no cover
    client: TestClient,
    generation_id: str,
) -> dict[str, int]:
    headers = _headers(OTHER_OWNER_ID)
    metadata = client.get(
        f"/api/v1/generations/{generation_id}",
        headers=headers,
    )
    content = client.get(
        f"/api/v1/generations/{generation_id}/content",
        headers=headers,
    )
    return {
        "metadata_status_code": metadata.status_code,
        "content_status_code": content.status_code,
    }


def _headers(
    subject_id: str,
    *,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience=SERVICE_ID)
    headers = {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
        "X-NEX-Tenant-ID": TENANT_ID,
        "X-NEX-Subject-ID": subject_id,
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _smoke_access_context() -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id=TENANT_ID,
        subject_id=OWNER_ID,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        scopes=("service:call",),
    )


def _safe_generation_observation(
    generation: Mapping[str, Any],
    replay: Mapping[str, Any],
    reads: Mapping[str, Any],
    provider_response: Mapping[str, Any] | None,
) -> dict[str, Any]:
    metadata = reads["metadata"]
    content = reads["content"]
    return {
        "cx_generation_id": generation.get("cx_generation_id"),
        "status": generation.get("status"),
        "replay_generation_id": replay.get("cx_generation_id"),
        "replay_status": replay.get("status"),
        "read_model_schema_version": metadata.get("read_model_schema_version"),
        "content_schema_version": content.get("content_schema_version"),
        "output_sha256": content.get("content_sha256"),
        "output_size_bytes": content.get("size_bytes"),
        "content_hash_matches": (
            content.get("content_sha256")
            == metadata.get("content_ref", {}).get("content_sha256")
        ),
        "owner_scope_enforced": content.get("owner_scope_enforced") is True,
        "provider_model": (
            provider_response.get("model_revision")
            if isinstance(provider_response, Mapping)
            else None
        ),
    }


def _safe_provider_observation(telemetry: Mapping[str, Any]) -> dict[str, int]:
    item = next(
        (
            candidate
            for candidate in telemetry.get("data", [])
            if isinstance(candidate, Mapping)
            and candidate.get("capability") == "generation"
        ),
        {},
    )
    return {
        "success_count": int(item.get("success_count", 0)),
        "failure_count": int(item.get("failure_count", 0)),
    }


def _read_database_identity(engine: Any) -> dict[str, str]:  # pragma: no cover
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT current_database() AS database, current_user AS role")
        ).mappings().one()
    return {"database": str(row["database"]), "role": str(row["role"])}


def _seed_retrieval_package(engine: Any) -> None:  # pragma: no cover
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO cx_retrieval_packages (
                    retrieval_package_id,
                    retrieval_package_schema_version,
                    package_hash,
                    status,
                    trace_id,
                    request_id,
                    query_text_sha256,
                    query_text_preview,
                    query_embedding_provided,
                    query_embedding_sha256,
                    query_embedding_dimension,
                    purpose,
                    retrieval_policy_id,
                    retrieval_policy_version,
                    retrieval_policy_hash,
                    retrieval_policy_source,
                    ranker_mix,
                    rerank_state,
                    permission_snapshot_hash,
                    source_summary,
                    score_summary,
                    warning_count,
                    evidence_count,
                    no_answer_reason,
                    tenant_ref_type,
                    tenant_ref_id,
                    owner_subject_ref_type,
                    owner_subject_ref_id
                ) VALUES (
                    :retrieval_package_id,
                    'cx_retrieval_context_package.v1',
                    :package_hash,
                    'READY',
                    :trace_id,
                    :request_id,
                    :query_text_sha256,
                    NULL,
                    false,
                    NULL,
                    0,
                    'grounded_answer',
                    'retrieval_quality_v1',
                    'v1',
                    :retrieval_policy_hash,
                    'protected-smoke',
                    'weighted_rrf_vector_bm25_with_rerank',
                    'APPLIED',
                    :permission_snapshot_hash,
                    CAST(:source_summary AS JSONB),
                    CAST(:score_summary AS JSONB),
                    0,
                    1,
                    NULL,
                    'oa.tenant',
                    :tenant_id,
                    'oa.user',
                    :owner_id
                )
                ON CONFLICT (retrieval_package_id) DO NOTHING
                """
            ),
            {
                "retrieval_package_id": RETRIEVAL_PACKAGE_ID,
                "package_hash": RETRIEVAL_PACKAGE_HASH,
                "trace_id": TRACE_ID,
                "request_id": REQUEST_ID,
                "query_text_sha256": hashlib.sha256(
                    PRIVATE_PROMPT_MARKER.encode("utf-8")
                ).hexdigest(),
                "retrieval_policy_hash": "a" * 64,
                "permission_snapshot_hash": "b" * 64,
                "source_summary": json.dumps(
                    {"source_count": 1, "document_count": 1, "chunk_count": 1},
                    sort_keys=True,
                ),
                "score_summary": json.dumps(
                    {"best_score": 0.99, "confidence_bucket": "READY"},
                    sort_keys=True,
                ),
                "tenant_id": TENANT_ID,
                "owner_id": OWNER_ID,
            },
        )


def _read_database_observation(  # pragma: no cover
    engine: Any,
    generation_id: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        execution = connection.execute(
            text(
                """
                SELECT count(*) AS row_count,
                       min(status) AS status,
                       min(owner_subject_ref_id) AS owner_subject_ref_id,
                       min(output_sha256) AS output_sha256,
                       min(output_size_bytes) AS output_size_bytes
                FROM cx_generation_executions
                WHERE cx_generation_id = :generation_id
                """
            ),
            {"generation_id": generation_id},
        ).mappings().one()
        admission = connection.execute(
            text(
                """
                SELECT count(*) AS row_count, min(status) AS status
                FROM cx_gen_admissions
                WHERE cx_generation_id = :generation_id
                """
            ),
            {"generation_id": generation_id},
        ).mappings().one()
        retrieval_package_count = int(
            connection.execute(
                text(
                    """
                    SELECT count(*) FROM cx_retrieval_packages
                    WHERE retrieval_package_id = :retrieval_package_id
                      AND tenant_ref_id = :tenant_id
                      AND owner_subject_ref_id = :owner_id
                    """
                ),
                {
                    "retrieval_package_id": RETRIEVAL_PACKAGE_ID,
                    "tenant_id": TENANT_ID,
                    "owner_id": OWNER_ID,
                },
            ).scalar_one()
        )
    return {
        "execution_count": int(execution["row_count"]),
        "execution_status": execution["status"],
        "owner_subject_ref_id": execution["owner_subject_ref_id"],
        "output_sha256": execution["output_sha256"],
        "output_size_bytes": int(execution["output_size_bytes"] or 0),
        "admission_count": int(admission["row_count"]),
        "admission_status": admission["status"],
        "retrieval_package_count": retrieval_package_count,
    }


def _read_event_observation(  # pragma: no cover
    event_store: SqlAlchemyOperationalEventStore,
    generation_id: str,
) -> dict[str, Any]:
    events = event_store.list_events(
        service_id=SERVICE_ID,
        trace_id=TRACE_ID,
        limit=50,
    )
    matched = [
        event
        for event in events
        if event.get("subject_ref")
        == {"type": "cx.generation", "id": generation_id}
    ]
    counts = Counter(str(event["event_type"]) for event in matched)
    return {
        "event_count": len(matched),
        "completed_count": counts[CX_GENERATION_COMPLETED_EVENT],
        "replayed_count": counts[CX_GENERATION_REPLAYED_EVENT],
        "metadata_only": all(
            PRIVATE_EVIDENCE_MARKER not in json.dumps(event, sort_keys=True)
            and PRIVATE_PROMPT_MARKER not in json.dumps(event, sort_keys=True)
            and "output_storage_uri" not in json.dumps(event, sort_keys=True)
            for event in matched
        ),
    }


def _checks(
    *,
    identity: Mapping[str, Any],
    generation: Mapping[str, Any],
    owner_isolation: Mapping[str, Any],
    provider: Mapping[str, Any],
    database: Mapping[str, Any],
    events: Mapping[str, Any],
) -> dict[str, bool]:
    generation_id = generation.get("cx_generation_id")
    output_hash = generation.get("output_sha256")
    output_size = int(generation.get("output_size_bytes") or 0)
    return {
        "test_database_identity": identity
        == {"database": EXPECTED_DATABASE, "role": EXPECTED_ROLE},
        "grounded_generation_completed": generation.get("status") == "COMPLETED",
        "restart_replay_same_execution": (
            generation_id == generation.get("replay_generation_id")
            and generation.get("replay_status") == "COMPLETED"
        ),
        "restart_metadata_reloaded": (
            generation.get("read_model_schema_version")
            == "cx_generation_read_model.v1"
        ),
        "restart_private_content_verified": (
            generation.get("content_schema_version") == "cx_generation_content.v1"
            and generation.get("content_hash_matches") is True
            and generation.get("owner_scope_enforced") is True
            and isinstance(output_hash, str)
            and len(output_hash) == 64
            and output_size > 0
        ),
        "cross_owner_hidden": (
            owner_isolation.get("metadata_status_code") == 404
            and owner_isolation.get("content_status_code") == 404
        ),
        "single_live_provider_call": (
            provider.get("success_count") == 1
            and provider.get("failure_count") == 0
        ),
        "current_generation_model_observed": (
            generation.get("provider_model") == EXPECTED_GENERATION_MODEL
        ),
        "execution_persisted_once": (
            database.get("execution_count") == 1
            and database.get("execution_status") == "COMPLETED"
            and database.get("owner_subject_ref_id") == OWNER_ID
            and database.get("output_sha256") == output_hash
            and database.get("output_size_bytes") == output_size
        ),
        "admission_terminal_once": (
            database.get("admission_count") == 1
            and database.get("admission_status") == "COMPLETED"
        ),
        "retrieval_lineage_persisted": database.get("retrieval_package_count") == 1,
        "terminal_events_persisted": (
            events.get("completed_count") == 1
            and events.get("replayed_count") == 1
            and events.get("metadata_only") is True
        ),
    }


def _cleanup(  # pragma: no cover - protected evidence
    *,
    engine: Any,
    private_store: FileSystemCxPrivateTextStore,
    access_context: CxAccessContext,
    generation_id: str | None,
) -> dict[str, Any]:
    output_deleted = False
    if generation_id is not None:
        key = build_private_payload_key(
            access_context,
            payload_kind=GENERATION_OUTPUT_PAYLOAD_KIND,
            content_id=generation_id,
        )
        output_deleted = private_store.delete_text(
            access_context=access_context,
            key=key,
        )

    key_hash = generation_idempotency_key_hash(IDEMPOTENCY_KEY)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM service_operational_events
                WHERE service_id = :service_id AND trace_id = :trace_id
                """
            ),
            {"service_id": SERVICE_ID, "trace_id": TRACE_ID},
        )
        connection.execute(
            text(
                """
                DELETE FROM cx_generation_executions
                WHERE cx_generation_id IN (
                    SELECT cx_generation_id
                    FROM cx_gen_admissions
                    WHERE tenant_ref_id = :tenant_id
                      AND owner_subject_ref_id = :owner_id
                      AND idempotency_key_hash = :key_hash
                )
                """
            ),
            {"tenant_id": TENANT_ID, "owner_id": OWNER_ID, "key_hash": key_hash},
        )
        connection.execute(
            text(
                """
                DELETE FROM cx_retrieval_packages
                WHERE retrieval_package_id = :retrieval_package_id
                  AND tenant_ref_id = :tenant_id
                  AND owner_subject_ref_id = :owner_id
                """
            ),
            {
                "retrieval_package_id": RETRIEVAL_PACKAGE_ID,
                "tenant_id": TENANT_ID,
                "owner_id": OWNER_ID,
            },
        )
        connection.execute(
            text(
                """
                DELETE FROM cx_gen_admissions
                WHERE tenant_ref_id = :tenant_id
                  AND owner_subject_ref_id = :owner_id
                  AND idempotency_key_hash = :key_hash
                """
            ),
            {"tenant_id": TENANT_ID, "owner_id": OWNER_ID, "key_hash": key_hash},
        )
        remaining_execution = int(
            connection.execute(
                text(
                    """
                    SELECT count(*) FROM cx_generation_executions
                    WHERE tenant_ref_id = :tenant_id
                      AND owner_subject_ref_id = :owner_id
                      AND trace_id = :trace_id
                    """
                ),
                {"tenant_id": TENANT_ID, "owner_id": OWNER_ID, "trace_id": TRACE_ID},
            ).scalar_one()
        )
        remaining_admission = int(
            connection.execute(
                text(
                    """
                    SELECT count(*) FROM cx_gen_admissions
                    WHERE tenant_ref_id = :tenant_id
                      AND owner_subject_ref_id = :owner_id
                      AND idempotency_key_hash = :key_hash
                    """
                ),
                {"tenant_id": TENANT_ID, "owner_id": OWNER_ID, "key_hash": key_hash},
            ).scalar_one()
        )
        remaining_retrieval_package = int(
            connection.execute(
                text(
                    """
                    SELECT count(*) FROM cx_retrieval_packages
                    WHERE retrieval_package_id = :retrieval_package_id
                    """
                ),
                {"retrieval_package_id": RETRIEVAL_PACKAGE_ID},
            ).scalar_one()
        )
    return {
        "private_output_deleted": output_deleted,
        "remaining_execution_count": remaining_execution,
        "remaining_admission_count": remaining_admission,
        "remaining_retrieval_package_count": remaining_retrieval_package,
        "database_rows_removed": (
            remaining_execution == 0
            and remaining_admission == 0
            and remaining_retrieval_package == 0
        ),
    }


def assert_evidence_redacted(
    evidence: object,
    env: Mapping[str, str],
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    for marker in (PRIVATE_EVIDENCE_MARKER, PRIVATE_PROMPT_MARKER):
        if marker in serialized:
            raise ValueError("Protected evidence contains private grounded content.")
    if "nex-cx-s97-live-" in serialized or "cx-private://" in serialized:
        raise ValueError("Protected evidence contains a private storage location.")
    for key in PROTECTED_ENV_KEYS:
        secret = _secret_fragment(key, env.get(key))
        if secret is not None and secret in serialized:
            raise ValueError(f"Protected evidence contains a protected value: {key}")


def _secret_fragment(key: str, value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if key == "NEX_CX_TEST_DATABASE_URL":
        if "@" not in value:
            return None
        authority = value.split("@", maxsplit=1)[0]
        if "://" in authority:
            authority = authority.split("://", maxsplit=1)[1]
        if ":" not in authority:
            return None
        password = authority.rsplit(":", maxsplit=1)[1]
        return password if len(password) >= 4 else None
    return value if len(value) >= 4 else None


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    diagnostics: Mapping[str, Any] | None = None,
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
        result["diagnostics"] = dict(diagnostics)
    return result


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = evidence.get("status")
    if status == "SKIPPED":
        return f"cx_grounded_generation_live_postgres=skipped reason={SMOKE_ENV}"
    if status == "PASS":
        generation = evidence["generation_observation"]
        provider = evidence["provider_observation"]
        return (
            "cx_grounded_generation_live_postgres=pass "
            f"db={evidence['database_identity']['database']} "
            f"generation={generation['status']} "
            f"model={generation['provider_model']} "
            f"provider_calls={provider['success_count']}"
        )
    diagnostics = evidence.get("diagnostics", {})
    return (
        "cx_grounded_generation_live_postgres=fail "
        f"code={evidence.get('failure_code', 'unknown')} "
        f"stage={diagnostics.get('stage', 'unknown')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run owner-private grounded generation through CX PostgreSQL and "
            "the protected DGX generation provider."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_env_file(ROOT / ".env")
    args = build_parser().parse_args(argv)
    evidence = run_cx_grounded_generation_live_postgres_smoke()
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
