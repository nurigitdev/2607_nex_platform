#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

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
from nex_cx.chunking import store_chunk_set  # noqa: E402
from nex_cx.embedding_index import DEFAULT_EMBEDDING_ALIAS  # noqa: E402
from nex_cx.ingestion import (  # noqa: E402
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    run_text_extraction_job,
)
from nex_cx.lexical_index import build_and_store_lexical_index  # noqa: E402
from nex_cx.mvp_runtime import build_cx_mvp_runtime  # noqa: E402
from nex_cx.pgvector_store import build_pgvector_cx_vector_store  # noqa: E402
from nex_cx.private_text_store import FileSystemCxPrivateTextStore  # noqa: E402
from nex_cx.repository import SqlAlchemyCxContentRepository  # noqa: E402
from nex_cx.retrieval import (  # noqa: E402
    DEFAULT_RERANKER_ALIAS,
    register_retrieval_routes,
)
from nex_cx.retrieval_observability import (  # noqa: E402
    CX_RETRIEVAL_PACKAGE_OBSERVED_EVENT,
)
from nex_cx.retrieval_confidence_calibration import (  # noqa: E402
    DEFAULT_RETRIEVAL_CONFIDENCE_WEIGHTS,
    RETRIEVAL_CONFIDENCE_POLICY_ID,
    build_retrieval_confidence_profile,
    project_retrieval_confidence_features,
)
from nex_cx.vector_index_repository import (  # noqa: E402
    SqlAlchemyVectorIndexRepository,
)
from nex_mo.providers import register_mock_provider_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    OperationalEventEmitter,
    SERVICE_SPECS,
    SqlAlchemyOperationalEventStore,
    build_engine,
    build_service_app,
    build_session_factory,
    evaluate_binary_score_calibration,
    issue_mock_service_token,
    redact_database_url,
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
from run_protected_live_rag_smoke import (  # noqa: E402
    InProcessLiveMoClient,
    patched_environ,
    patched_remote_request,
    read_provider_telemetry,
)


SCHEMA_VERSION = "s136_permission_hybrid_live_postgres_smoke.v1"
SMOKE_ENV = "NEX_S136_PERMISSION_HYBRID_LIVE_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_S136_PERMISSION_HYBRID_LIVE_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = "nex-cx"
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"
EXPECTED_MODELS = {
    "embedding": "Qwen3-Embedding-4B",
    "reranking": "Qwen3-Reranker-4B",
}
TENANT_ID = "s136-live-tenant"
OWNER_ID = "s136-live-owner"
OTHER_OWNER_ID = "s136-live-other-owner"
CALIBRATION_DATASET_PATH = (
    ROOT / "scripts" / "smoke" / "data" / "s136_multisignal_calibration_v1.json"
)
SOURCE_MARKER = "S136_PRIVATE_HYBRID_SOURCE"
NO_ANSWER_QUERY = "zxqv136nomatchtoken"
PROTECTED_ENV_KEYS = (
    "NEX_CX_TEST_DATABASE_URL",
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
)

HttpRequester = Callable[..., Any]
SmokeExecutor = Callable[..., dict[str, Any]]


def run_s136_permission_hybrid_live_postgres_smoke(
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
    if env.get(PROFILE_ENV, "test") != "test":
        return _failure("profile_not_allowed", f"{PROFILE_ENV} must be test.")
    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
    }
    issues = _configuration_issues(effective_env)
    if issues:
        return _failure("configuration_invalid", issues)

    database_url = ""
    try:
        database_env = service_database_env(SERVICE_ID, profile="test")
        database_url = service_database_url(
            SERVICE_ID,
            profile="test",
            environ=effective_env,
        )
        if not _target_url_allowed(database_url):
            return _failure("target_not_allowed", "nex_cx_test target is required.")
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile="test",
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
        if execution.get("failed_checks"):
            return _failure(
                "live_acceptance_failed",
                list(execution["failed_checks"]),
                execution=execution,
            )
        result = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": "test",
            "redacted_database_url": redact_database_url(database_url),
            "migration": {
                "planned_count": len(migration.planned),
                "applied_count": len(migration.applied),
                "skipped_count": len(migration.skipped),
            },
            "provider_path": "cx_production_runtime_to_mo_live_alias",
            **execution,
        }
    except (MigrationError, ValueError) as exc:
        result = _failure("configuration_invalid", exc.__class__.__name__)
    except Exception as exc:  # pragma: no cover - protected live evidence
        result = _failure("execution_failed", exc.__class__.__name__)
    _assert_redacted(result, effective_env)
    return result


def _execute_live_smoke(  # pragma: no cover - protected PostgreSQL/DGX evidence
    *,
    database_url: str,
    database_env: str,
    runtime_environ: dict[str, str],
    requester: HttpRequester | None,
) -> dict[str, Any]:
    probe = uuid4().hex
    trace_id = uuid4().hex
    engine = build_engine(database_url)
    factory = build_session_factory(engine)
    repository = SqlAlchemyCxContentRepository(factory)
    vector_repository = SqlAlchemyVectorIndexRepository(factory)
    store = ContentIngestionStore(content_repository=repository)
    event_store = SqlAlchemyOperationalEventStore(factory)
    emitter = OperationalEventEmitter(service_id=SERVICE_ID, store=event_store)
    document_ids: list[str] = []
    source_file_ids: list[str] = []
    vector_index_ids: list[str] = []
    retrieval_package_ids: list[str] = []
    checks: dict[str, bool] = {}
    lifecycle: dict[str, Any] = {}
    provider_observation: dict[str, Any] = {}
    dataset = _load_calibration_dataset(CALIBRATION_DATASET_PATH)
    calibration_evaluation: dict[str, Any] = {}
    calibration_profile: dict[str, Any] | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="nex-cx-s136-live-") as temp_dir:
            root = Path(temp_dir)
            storage = _storage_config(root)
            private_store = FileSystemCxPrivateTextStore(root / "private")
            vector_store_api = build_pgvector_cx_vector_store(
                database_env=database_env,
                environ=runtime_environ,
                workload="api",
            )
            vector_store_worker = build_pgvector_cx_vector_store(
                database_env=database_env,
                environ=runtime_environ,
                workload="worker",
            )
            mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
            register_mock_provider_routes(mo_app)
            with patched_environ(runtime_environ):
                with patched_remote_request(requester):
                    remote_provider.reset_remote_provider_telemetry()
                    with TestClient(mo_app) as mo_test_client:
                        mo_client = InProcessLiveMoClient(mo_test_client)
                        composition = build_cx_mvp_runtime(
                            session_factory=factory,
                            store=store,
                            storage_config=storage,
                            content_repository=repository,
                            vector_repository=vector_repository,
                            retrieval_vector_store=vector_store_api,
                            ingestion_vector_store=vector_store_worker,
                            private_text_store=private_store,
                            embedding_client=mo_client,
                            embedding_alias=DEFAULT_EMBEDDING_ALIAS,
                            rerank_client=mo_client,
                            reranker_alias=DEFAULT_RERANKER_ALIAS,
                        )
                        calibration_app = build_service_app(SERVICE_SPECS[SERVICE_ID])
                        register_retrieval_routes(
                            calibration_app,
                            store=store,
                            hybrid_runtime=composition.hybrid_retrieval_runtime,
                            event_emitter=emitter,
                        )
                        with TestClient(calibration_app) as calibration_client:
                            indexed = _ingest_document(
                                probe=probe,
                                label="indexed",
                                source_text=(
                                    f"{SOURCE_MARKER}_{probe} "
                                    f"{dataset['source_text']}"
                                ),
                                request_id=f"s136-index-{probe}",
                                trace_id=trace_id,
                                store=store,
                                storage=storage,
                            )
                            document_ids.append(indexed["document_id"])
                            source_file_ids.append(indexed["source_file_id"])
                            index_result = composition.ingestion_vector_indexer(
                                {
                                    "document_id": indexed["document_id"],
                                    "job_id": indexed["job_id"],
                                    "idempotency_key": indexed["upload_id"],
                                    "tenant_ref": {"type": "oa.tenant", "id": TENANT_ID},
                                    "owner_subject_ref": {"type": "oa.user", "id": OWNER_ID},
                                    "request_id": f"s136-index-{probe}",
                                    "trace_id": trace_id,
                                    "created_at": indexed["created_at"],
                                    "updated_at": indexed["updated_at"],
                                }
                            )
                            vector_index_ids.append(index_result.output_ref.split(":", 1)[1])
                            unindexed = _ingest_document(
                                probe=probe,
                                label="unindexed",
                                source_text=f"{SOURCE_MARKER}_{probe} 별도의 일반 운영 문서입니다.",
                                request_id=f"s136-noanswer-{probe}",
                                trace_id=trace_id,
                                store=store,
                                storage=storage,
                            )
                            document_ids.append(unindexed["document_id"])
                            source_file_ids.append(unindexed["source_file_id"])
                            calibration_samples, model_bindings, package_ids = (
                                _collect_calibration_samples(
                                    calibration_client,
                                    cases=dataset["calibration_cases"],
                                    document_id=indexed["document_id"],
                                    probe=probe,
                                    trace_id=trace_id,
                                )
                            )
                            retrieval_package_ids.extend(package_ids)
                        calibration_evaluation = evaluate_binary_score_calibration(
                            calibration_samples,
                            dataset_id=str(dataset["dataset_id"]),
                        )
                        stable_binding = (
                            len(model_bindings) == 1
                            and next(iter(model_bindings), None)
                            == (
                                EXPECTED_MODELS["embedding"],
                                EXPECTED_MODELS["reranking"],
                            )
                        )
                        if calibration_evaluation.get("status") == "PASSED" and stable_binding:
                            calibration_profile = build_retrieval_confidence_profile(
                                profile_id=(
                                    "qwen3-embedding-4b-qwen3-reranker-4b-"
                                    "weighted-rrf-v1"
                                ),
                                version="0001",
                                status="ACTIVE",
                                embedding_model_revision=EXPECTED_MODELS["embedding"],
                                reranker_model_revision=EXPECTED_MODELS["reranking"],
                                ranking_policy_id="weighted_rrf_vector_bm25_v1",
                                weights=DEFAULT_RETRIEVAL_CONFIDENCE_WEIGHTS,
                                evaluation=calibration_evaluation,
                            )
                        calibrated_runtime = replace(
                            composition.hybrid_retrieval_runtime,
                            confidence_profiles=(
                                (calibration_profile,)
                                if calibration_profile is not None
                                else ()
                            ),
                            require_calibrated_confidence=True,
                        )
                        cx_app = build_service_app(SERVICE_SPECS[SERVICE_ID])
                        register_retrieval_routes(
                            cx_app,
                            store=store,
                            hybrid_runtime=calibrated_runtime,
                            event_emitter=emitter,
                        )
                        with TestClient(cx_app) as client:
                            ready_response = _retrieve(
                                client,
                                query=dataset["validation_cases"]["ready"],
                                document_id=indexed["document_id"],
                                owner_id=OWNER_ID,
                                request_id=f"s136-ready-{probe}",
                                trace_id=trace_id,
                            )
                            ready = ready_response.json()
                            retrieval_package_ids.append(ready["retrieval_package_id"])
                            low_response = _retrieve(
                                client,
                                query=dataset["validation_cases"]["low_confidence"],
                                document_id=indexed["document_id"],
                                owner_id=OWNER_ID,
                                request_id=f"s136-low-{probe}",
                                trace_id=trace_id,
                            )
                            low = low_response.json()
                            retrieval_package_ids.append(low["retrieval_package_id"])
                            no_answer_response = _retrieve(
                                client,
                                query=NO_ANSWER_QUERY,
                                document_id=unindexed["document_id"],
                                owner_id=OWNER_ID,
                                request_id=f"s136-none-{probe}",
                                trace_id=trace_id,
                            )
                            no_answer = no_answer_response.json()
                            retrieval_package_ids.append(no_answer["retrieval_package_id"])
                            before_denial = read_provider_telemetry(
                                mo_test_client,
                                trace_id,
                                f"s136-telemetry-before-{probe}",
                            )
                            denied_response = _retrieve(
                                client,
                                query=dataset["validation_cases"]["ready"],
                                document_id=indexed["document_id"],
                                owner_id=OTHER_OWNER_ID,
                                request_id=f"s136-denied-{probe}",
                                trace_id=trace_id,
                            )
                            after_denial = read_provider_telemetry(
                                mo_test_client,
                                trace_id,
                                f"s136-telemetry-after-{probe}",
                            )

            provider_observation = _provider_observation(after_denial)
            persisted = [
                _read_persisted_result(engine, package_id)
                for package_id in retrieval_package_ids
            ]
            restart_engine = build_engine(database_url)
            try:
                restart_persisted = [
                    _read_persisted_result(restart_engine, package_id)
                    for package_id in retrieval_package_ids
                ]
                restart_identity = _database_identity(restart_engine)
            finally:
                restart_engine.dispose()
            observed_events = event_store.list_events(
                event_type=CX_RETRIEVAL_PACKAGE_OBSERVED_EVENT,
                trace_id=trace_id,
                limit=50,
            )
            ready_profile = ready.get("retrieval_profile", {})
            candidate_summary = ready_profile.get("candidate_summary", {})
            quality_policy = ready_profile.get("quality_policy", {})
            embedding_profile = ready_profile.get("embedding_profile", {})
            reranker_profile = ready_profile.get("reranker_profile", {})
            checks.update(
                {
                    "test_database_identity": _database_identity(engine)
                    == {"database": EXPECTED_DATABASE, "role": EXPECTED_ROLE},
                    "multisignal_calibration_passed": (
                        calibration_evaluation.get("status") == "PASSED"
                        and calibration_evaluation.get("sample_count") == 20
                        and calibration_profile is not None
                        and calibration_profile.get("status") == "ACTIVE"
                    ),
                    "calibration_binding_exact": (
                        calibration_profile is not None
                        and calibration_profile.get("binding", {}).get(
                            "embedding_model_revision"
                        )
                        == EXPECTED_MODELS["embedding"]
                        and calibration_profile.get("binding", {}).get(
                            "reranker_model_revision"
                        )
                        == EXPECTED_MODELS["reranking"]
                    ),
                    "production_runtime_ready": (
                        ready_response.status_code == 200
                        and ready.get("status") == "READY"
                    ),
                    "permission_scope_exact": (
                        ready.get("permission_snapshot", {})
                        .get("scope_applied", {})
                        .get("document_ids")
                        == [indexed["document_id"]]
                    ),
                    "postgres_bm25_and_pgvector_candidates": (
                        candidate_summary.get("bm25_candidate_count", 0) >= 1
                        and candidate_summary.get("vector_candidate_count", 0) >= 1
                        and candidate_summary.get("fused_candidate_count", 0) >= 1
                    ),
                    "weighted_rrf_policy": (
                        quality_policy.get("vector_weight") == 0.7
                        and quality_policy.get("bm25_weight") == 0.3
                        and quality_policy.get("rrf_k") == 60
                    ),
                    "live_provider_models": (
                        embedding_profile.get("model_revision")
                        == EXPECTED_MODELS["embedding"]
                        and reranker_profile.get("model_revision")
                        == EXPECTED_MODELS["reranking"]
                        and ready.get("score_summary", {}).get("rerank_state")
                        == "APPLIED"
                    ),
                    "low_confidence_classified": (
                        low_response.status_code == 200
                        and low.get("status") == "LOW_CONFIDENCE"
                        and calibration_profile is not None
                        and low.get("score_summary", {}).get("best_score", 1.0)
                        < calibration_profile["threshold"]
                    ),
                    "active_calibration_profile_applied": (
                        calibration_profile is not None
                        and ready.get("score_summary", {}).get(
                            "confidence_policy_id"
                        )
                        == RETRIEVAL_CONFIDENCE_POLICY_ID
                        and ready.get("score_summary", {}).get(
                            "calibration_profile_hash"
                        )
                        == calibration_profile.get("profile_hash")
                    ),
                    "no_answer_without_rerank": (
                        no_answer_response.status_code == 200
                        and no_answer.get("status") == "NO_ANSWER"
                        and no_answer.get("score_summary", {}).get("rerank_state")
                        == "NOT_APPLIED"
                        and no_answer.get("evidence_items") == []
                    ),
                    "cross_owner_hidden_before_provider": (
                        denied_response.status_code == 404
                        and _provider_counts(before_denial)
                        == _provider_counts(after_denial)
                    ),
                    "provider_telemetry_live": all(
                        provider_observation[capability]["success_count"] >= 1
                        and provider_observation[capability]["failure_count"] == 0
                        and provider_observation[capability]["model"] == model
                        for capability, model in EXPECTED_MODELS.items()
                    ),
                    "hash_only_postgres_persistence": (
                        len(persisted) == len(retrieval_package_ids) == 23
                        and all(item.get("query_text_preview") is None for item in persisted)
                        and all(item.get("query_text_sha256") for item in persisted)
                    ),
                    "restart_readback_complete": (
                        restart_identity
                        == {"database": EXPECTED_DATABASE, "role": EXPECTED_ROLE}
                        and restart_persisted == persisted
                    ),
                    "operations_evidence_v2": any(
                        event.get("details", {}).get("observability_schema_version")
                        == "cx_retrieval_observability.v2"
                        and event.get("details", {}).get("embedding_model_revision")
                        == EXPECTED_MODELS["embedding"]
                        and event.get("details", {}).get("reranker_model_revision")
                        == EXPECTED_MODELS["reranking"]
                        and calibration_profile is not None
                        and event.get("details", {}).get(
                            "calibration_profile_hash"
                        )
                        == calibration_profile.get("profile_hash")
                        for event in observed_events
                    ),
                }
            )
            lifecycle = {
                "indexed_document_sha256": _digest(indexed["document_id"]),
                "unindexed_document_sha256": _digest(unindexed["document_id"]),
                "ready_package_sha256": _digest(ready["retrieval_package_id"]),
                "ready_status": ready.get("status"),
                "low_confidence_status": low.get("status"),
                "no_answer_status": no_answer.get("status"),
                "denied_status_code": denied_response.status_code,
                "ready_best_score": ready.get("score_summary", {}).get("best_score"),
                "low_best_score": low.get("score_summary", {}).get("best_score"),
                "calibration_threshold": (
                    calibration_profile.get("threshold")
                    if calibration_profile is not None
                    else None
                ),
                "calibration_profile_hash": (
                    calibration_profile.get("profile_hash")
                    if calibration_profile is not None
                    else None
                ),
            }
    finally:
        _cleanup(
            engine,
            trace_id=trace_id,
            retrieval_package_ids=retrieval_package_ids,
            vector_index_ids=vector_index_ids,
            document_ids=document_ids,
            source_file_ids=source_file_ids,
        )
        checks["cleanup_complete"] = _cleanup_complete(
            engine,
            retrieval_package_ids=retrieval_package_ids,
            vector_index_ids=vector_index_ids,
            document_ids=document_ids,
            source_file_ids=source_file_ids,
        )
        engine.dispose()
    return {
        "database_identity": {"database": EXPECTED_DATABASE, "role": EXPECTED_ROLE},
        "provider_observation": provider_observation,
        "calibration": {
            "dataset_id": calibration_evaluation.get("dataset_id"),
            "dataset_sha256": calibration_evaluation.get("dataset_sha256"),
            "status": calibration_evaluation.get("status"),
            "sample_count": calibration_evaluation.get("sample_count"),
            "positive_count": calibration_evaluation.get("positive_count"),
            "negative_count": calibration_evaluation.get("negative_count"),
            "selected_threshold": calibration_evaluation.get(
                "selected_threshold"
            ),
            "selected_metrics": calibration_evaluation.get("selected_metrics"),
            "profile_id": (
                calibration_profile.get("profile_id")
                if calibration_profile is not None
                else None
            ),
            "profile_hash": (
                calibration_profile.get("profile_hash")
                if calibration_profile is not None
                else None
            ),
        },
        "lifecycle": lifecycle,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _load_calibration_dataset(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    validation = payload.get("validation_cases") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("dataset_schema_version")
        != "cx_retrieval_multisignal_calibration_dataset.v1"
        or not isinstance(payload.get("dataset_id"), str)
        or not isinstance(payload.get("source_text"), str)
        or not payload["source_text"].strip()
        or not isinstance(payload.get("calibration_cases"), list)
        or len(payload["calibration_cases"]) < 20
        or not isinstance(validation, dict)
        or not all(
            isinstance(validation.get(key), str) and validation[key].strip()
            for key in ("ready", "low_confidence")
        )
    ):
        raise ValueError("S136 multisignal calibration dataset is invalid.")
    seen: set[str] = set()
    for case in payload["calibration_cases"]:
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("case_id"), str)
            or not case["case_id"].strip()
            or case["case_id"] in seen
            or not isinstance(case.get("query"), str)
            or not case["query"].strip()
            or not isinstance(case.get("expected_ready"), bool)
        ):
            raise ValueError("S136 multisignal calibration case is invalid.")
        seen.add(case["case_id"])
    return payload


def _collect_calibration_samples(
    client: TestClient,
    *,
    cases: list[dict[str, Any]],
    document_id: str,
    probe: str,
    trace_id: str,
) -> tuple[list[dict[str, Any]], set[tuple[str, str]], list[str]]:
    samples: list[dict[str, Any]] = []
    bindings: set[tuple[str, str]] = set()
    package_ids: list[str] = []
    for case in cases:
        response = _retrieve(
            client,
            query=case["query"],
            document_id=document_id,
            owner_id=OWNER_ID,
            request_id=f"s136-cal-{case['case_id']}-{probe}",
            trace_id=trace_id,
        )
        if response.status_code != 200:
            raise ValueError("Calibration retrieval request failed.")
        package = response.json()
        evidence_items = package.get("evidence_items")
        if not isinstance(evidence_items, list) or not evidence_items:
            raise ValueError("Calibration retrieval evidence is unavailable.")
        features = project_retrieval_confidence_features(evidence_items)
        samples.append(
            {
                "sample_id": case["case_id"],
                "expected_ready": case["expected_ready"],
                "score": features["composite_score"],
            }
        )
        profile = package.get("retrieval_profile", {})
        embedding_model = profile.get("embedding_profile", {}).get(
            "model_revision"
        )
        reranker_model = profile.get("reranker_profile", {}).get(
            "model_revision"
        )
        if isinstance(embedding_model, str) and isinstance(reranker_model, str):
            bindings.add((embedding_model, reranker_model))
        package_id = package.get("retrieval_package_id")
        if not isinstance(package_id, str) or not package_id:
            raise ValueError("Calibration retrieval package ID is invalid.")
        package_ids.append(package_id)
    return samples, bindings, package_ids


def _ingest_document(  # pragma: no cover - protected PostgreSQL evidence
    *,
    probe: str,
    label: str,
    source_text: str,
    request_id: str,
    trace_id: str,
    store: ContentIngestionStore,
    storage: CxStorageConfig,
) -> dict[str, str]:
    registration = build_upload_registration(
        {
            "filename": f"s136-{label}-{probe}.txt",
            "content_type": "text/plain",
            "content_text": source_text,
            "tenant_id": TENANT_ID,
            "owner_user_id": OWNER_ID,
            "uploaded_by_user_id": OWNER_ID,
        },
        storage_config=storage,
        request_id=request_id,
        trace_id=trace_id,
    )
    saved = store.save_upload_registration(registration, source_text=source_text)
    document_id = str(saved["document_id"])
    refs = store.get_content_ref(document_id)
    if refs is None:
        raise RuntimeError("content_lineage_unavailable")
    extraction = run_text_extraction_job(
        saved["extraction"]["job_id"],
        store=store,
        storage_config=storage,
        request_id=request_id,
        trace_id=trace_id,
    )
    store_chunk_set(
        document_id=document_id,
        extraction=extraction,
        markdown_text=Path(extraction["extracted_markdown_path"]).read_text(
            encoding="utf-8"
        ),
        store=store,
        storage_config=storage,
        request_id=request_id,
        trace_id=trace_id,
    )
    build_and_store_lexical_index(
        document_id,
        store=store,
        storage_config=storage,
        request_id=request_id,
        trace_id=trace_id,
    )
    return {
        "document_id": document_id,
        "source_file_id": str(refs["source_file_id"]),
        "job_id": str(saved["extraction"]["job_id"]),
        "upload_id": str(saved["upload_id"]),
        "created_at": str(saved["created_at"]),
        "updated_at": str(extraction["updated_at"]),
    }


def _retrieve(
    client: TestClient,
    *,
    query: str,
    document_id: str,
    owner_id: str,
    request_id: str,
    trace_id: str,
) -> Any:
    return client.post(
        "/api/v1/retrieval/context",
        json={
            "query_text": query,
            "document_scope": {"document_ids": [document_id]},
            "top_k": 3,
            "purpose": "grounded_answer",
        },
        headers=_headers(request_id, trace_id, owner_id),
    )


def _storage_config(root: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=root,
        source_root=root / "cx" / "source-files",
        extracted_markdown_root=root / "cx" / "extracted-markdown",
        extraction_temp_root=root / "cx" / "extraction-temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def _headers(request_id: str, trace_id: str, owner_id: str) -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ae-api",
        audience=SERVICE_ID,
    ).access_token
    return {
        "Authorization": f"Bearer {token}",
        "X-NEX-Tenant-ID": TENANT_ID,
        "X-NEX-Subject-ID": owner_id,
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _configuration_issues(environ: Mapping[str, str]) -> list[dict[str, str]]:
    required = PROTECTED_ENV_KEYS
    issues = [
        {"error_code": "configuration_missing", "field": key}
        for key in required
        if not str(environ.get(key, "")).strip()
    ]
    expected = {
        "NEX_MO_REMOTE_EMBEDDING_MODEL": EXPECTED_MODELS["embedding"],
        "NEX_MO_REMOTE_RERANKER_MODEL": EXPECTED_MODELS["reranking"],
        "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "openai_embeddings",
        "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE": "rerank",
    }
    issues.extend(
        {"error_code": "configuration_mismatch", "field": key}
        for key, value in expected.items()
        if str(environ.get(key, "")).strip() != value
    )
    return issues


def _provider_observation(telemetry: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for capability in EXPECTED_MODELS:
        item = next(
            (
                candidate
                for candidate in telemetry.get("data", [])
                if isinstance(candidate, Mapping)
                and candidate.get("capability") == capability
            ),
            {},
        )
        result[capability] = {
            "model": item.get("model_revision"),
            "success_count": int(item.get("success_count", 0)),
            "failure_count": int(item.get("failure_count", 0)),
        }
    return result


def _provider_counts(telemetry: Mapping[str, Any]) -> dict[str, tuple[int, int]]:
    observation = _provider_observation(telemetry)
    return {
        capability: (item["success_count"], item["failure_count"])
        for capability, item in observation.items()
    }


def _database_identity(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
) -> dict[str, str]:
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT current_database() AS database, current_user AS role")
        ).mappings().one()
    return {"database": str(row["database"]), "role": str(row["role"])}


def _read_persisted_result(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
    package_id: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT retrieval_package_id, query_text_sha256, "
                "query_text_preview, evidence_count FROM cx_retrieval_packages "
                "WHERE retrieval_package_id = :identifier"
            ),
            {"identifier": package_id},
        ).mappings().one_or_none()
    return dict(row) if row is not None else {}


def _cleanup(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
    *,
    trace_id: str,
    retrieval_package_ids: list[str],
    vector_index_ids: list[str],
    document_ids: list[str],
    source_file_ids: list[str],
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM service_operational_events WHERE trace_id = :trace_id"),
            {"trace_id": trace_id},
        )
        for identifier in retrieval_package_ids:
            connection.execute(
                text("DELETE FROM cx_retrieval_packages WHERE retrieval_package_id = :identifier"),
                {"identifier": identifier},
            )
        for identifier in vector_index_ids:
            connection.execute(
                text("DELETE FROM cx_vectors WHERE vector_index_id = :identifier"),
                {"identifier": identifier},
            )
            connection.execute(
                text("DELETE FROM cx_vector_indexes WHERE vector_index_id = :identifier"),
                {"identifier": identifier},
            )
        for identifier in document_ids:
            connection.execute(
                text("DELETE FROM cx_content_objects WHERE content_object_id = :identifier"),
                {"identifier": identifier},
            )
        for identifier in source_file_ids:
            connection.execute(
                text("DELETE FROM cx_source_files WHERE source_file_id = :identifier"),
                {"identifier": identifier},
            )


def _cleanup_complete(  # pragma: no cover - protected PostgreSQL evidence
    engine: Any,
    *,
    retrieval_package_ids: list[str],
    vector_index_ids: list[str],
    document_ids: list[str],
    source_file_ids: list[str],
) -> bool:
    targets = (
        ("cx_retrieval_packages", "retrieval_package_id", retrieval_package_ids),
        ("cx_vector_indexes", "vector_index_id", vector_index_ids),
        ("cx_content_objects", "content_object_id", document_ids),
        ("cx_source_files", "source_file_id", source_file_ids),
    )
    with engine.connect() as connection:
        for table_name, column_name, identifiers in targets:
            for identifier in identifiers:
                count = connection.execute(
                    text(
                        f"SELECT count(*) FROM {table_name} "
                        f"WHERE {column_name} = :identifier"
                    ),
                    {"identifier": identifier},
                ).scalar_one()
                if count != 0:
                    return False
    return True


def _target_url_allowed(database_url: str) -> bool:
    try:
        parsed = urlsplit(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
        return (
            unquote(parsed.username or "") == EXPECTED_ROLE
            and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
        )
    except ValueError:
        return False


def _assert_redacted(evidence: object, environ: Mapping[str, str]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    dataset = _load_calibration_dataset(CALIBRATION_DATASET_PATH)
    protected = [
        SOURCE_MARKER,
        NO_ANSWER_QUERY,
        dataset["source_text"],
        *(case["query"] for case in dataset["calibration_cases"]),
        *dataset["validation_cases"].values(),
    ]
    for key in PROTECTED_ENV_KEYS:
        value = str(environ.get(key, ""))
        if key == "NEX_CX_TEST_DATABASE_URL":
            try:
                value = unquote(urlsplit(value).password or "")
            except ValueError:
                value = ""
        protected.append(value)
    if any(len(value) >= 4 and value in serialized for value in protected):
        raise ValueError("S136 live evidence contains a protected value.")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _failure(
    code: str,
    detail: Any,
    *,
    execution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }
    if execution is not None:
        result["execution"] = dict(execution)
    return result


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "skipped":
        return f"s136_permission_hybrid_live_postgres=skipped reason={SMOKE_ENV}"
    if status == "pass":
        checks = result.get("checks", {})
        lifecycle = result.get("lifecycle", {})
        return (
            "s136_permission_hybrid_live_postgres=pass "
            f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
            f"decisions={lifecycle.get('ready_status')}/"
            f"{lifecycle.get('low_confidence_status')}/"
            f"{lifecycle.get('no_answer_status')} "
            "database=nex_cx_test providers=embedding,reranking"
        )
    return (
        "s136_permission_hybrid_live_postgres=fail "
        f"error={result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = run_s136_permission_hybrid_live_postgres_smoke()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            f"{json.dumps(result, indent=2, sort_keys=True)}\n",
            encoding="utf-8",
        )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
