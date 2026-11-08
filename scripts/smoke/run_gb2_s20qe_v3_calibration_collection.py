#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "quality",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_s136_permission_hybrid_live_postgres_smoke as s136
from check_model_calibration_dataset import (
    DEFAULT_V3_PATH,
    admit_calibration_dataset_files,
)
from nex_cx.embedding_index import DEFAULT_EMBEDDING_ALIAS
from nex_cx.ingestion import ContentIngestionStore
from nex_cx.mvp_runtime import build_cx_mvp_runtime
from nex_cx.pgvector_store import build_pgvector_cx_vector_store
from nex_cx.private_text_store import FileSystemCxPrivateTextStore
from nex_cx.repository import SqlAlchemyCxContentRepository
from nex_cx.retrieval import DEFAULT_RERANKER_ALIAS, register_retrieval_routes
from nex_cx.retrieval_confidence_candidate_diagnostics import (
    build_candidate_diagnostic_observations,
    build_candidate_feature_calibration_samples,
    diagnose_candidate_feature_correction,
)
from nex_cx.retrieval_confidence_feature_audit import (
    diagnose_mixed_candidate_feature_discriminativeness,
)
from nex_cx.retrieval_confidence_package_semantics import (
    build_mixed_candidate_calibration_sample,
)
from nex_cx.vector_index_repository import SqlAlchemyVectorIndexRepository
from nex_mo import remote_provider
from nex_mo.providers import register_mock_provider_routes
from nex_runtime import (
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    redact_database_url,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_migrations import (
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults
from run_protected_live_rag_smoke import (
    InProcessLiveMoClient,
    patched_environ,
    patched_remote_request,
    read_provider_telemetry,
)

SCHEMA_VERSION = "gb2_s20qe_v3_calibration_collection.v1"
SMOKE_ENV = "NEX_GB2_S20QE_V3_CALIBRATION_COLLECTION"
PROFILE_ENV = "NEX_GB2_S20QE_PROFILE"
REPEAT_COUNT_ENV = "NEX_GB2_S20QE_REPEAT_COUNT"
SERVICE_ID = "nex-cx"
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"
CALIBRATION_PARTITION = "CALIBRATION"
HOLDOUT_PARTITION = "HOLDOUT"
EXPECTED_CALIBRATION_SCENARIOS = 20
EXPECTED_CALIBRATION_PACKAGES = 40
EXPECTED_CALIBRATION_CANDIDATES = 160
TOKENIZER_POLICY_PREFIX = "cx-tokenizer-profile:"
TENANT_ID = s136.TENANT_ID
OWNER_ID = s136.OWNER_ID
PROTECTED_ENV_KEYS = (
    "NEX_CX_TEST_DATABASE_URL",
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
)

HttpRequester = Callable[..., Any]
CollectionExecutor = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class LiveCalibrationDatasetSpec:
    dataset_path: Path
    schema_version: str
    case_count: int
    calibration_scenario_count: int
    holdout_scenario_count: int
    request_prefix: str

    @property
    def calibration_package_count(self) -> int:
        return self.calibration_scenario_count * 2

    @property
    def calibration_candidate_count(self) -> int:
        return self.calibration_package_count * 4

    @property
    def holdout_protected_value_count(self) -> int:
        return self.holdout_scenario_count * 10


V3_DATASET_SPEC = LiveCalibrationDatasetSpec(
    dataset_path=DEFAULT_V3_PATH,
    schema_version="model_calibration_dataset.v3",
    case_count=60,
    calibration_scenario_count=EXPECTED_CALIBRATION_SCENARIOS,
    holdout_scenario_count=10,
    request_prefix="s20qe",
)


def run_gb2_s20qe_v3_calibration_collection(
    environ: Mapping[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
    executor: CollectionExecutor | None = None,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    if env.get(PROFILE_ENV, "test") != "test":
        return _failure("profile_not_allowed")

    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
    }
    issues = _configuration_issues(effective_env)
    if issues:
        return _failure("configuration_invalid", detail=issues)
    try:
        repeat_count = _repeat_count(effective_env.get(REPEAT_COUNT_ENV, "1"))
    except (TypeError, ValueError):
        return _failure("configuration_invalid", detail=REPEAT_COUNT_ENV)

    database_url = ""
    try:
        database_env = service_database_env(SERVICE_ID, profile="test")
        database_url = service_database_url(
            SERVICE_ID,
            profile="test",
            environ=effective_env,
        )
        if not s136._target_url_allowed(database_url):
            return _failure("target_not_allowed")
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile="test",
        )
    except (MigrationError, ValueError) as exc:
        result = _failure("configuration_invalid", detail=exc.__class__.__name__)
    else:
        execute = executor or _execute_live_collection
        try:
            execution = execute(
                database_url=database_url,
                database_env=database_env,
                runtime_environ={
                    **effective_env,
                    SERVICE_SPECS[SERVICE_ID].database_env: database_url,
                    "NEX_CX_PERSISTENCE_MODE": "postgres",
                },
                requester=requester,
                repeat_count=repeat_count,
            )
        except Exception as exc:  # noqa: BLE001  # pragma: no cover
            result = _failure(
                "execution_failed",
                detail={
                    "exception": exc.__class__.__name__,
                    "error_code": getattr(exc, "error_code", None),
                },
            )
        else:
            result = _result_from_execution(
                execution=execution,
                database_url=database_url,
                migration=migration,
            )
    _assert_redacted(result, effective_env)
    return result


def _result_from_execution(
    *,
    execution: Mapping[str, Any],
    database_url: str,
    migration: Any,
) -> dict[str, Any]:
    if execution.get("failed_checks"):
        return _failure(
            "live_collection_failed",
            detail=list(execution["failed_checks"]),
            execution=execution,
        )
    return {
        "evidence_schema_version": SCHEMA_VERSION,
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


def _execute_live_collection(  # pragma: no cover - PostgreSQL/DGX protected
    *,
    database_url: str,
    database_env: str,
    runtime_environ: dict[str, str],
    requester: HttpRequester | None,
    repeat_count: int = 1,
    dataset_spec: LiveCalibrationDatasetSpec = V3_DATASET_SPEC,
    dataset_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    admitted = (
        dict(dataset_manifest)
        if dataset_manifest is not None
        else dict(admit_calibration_dataset_files()["v3"])
    )
    dataset = _load_dataset(
        dataset_spec.dataset_path,
        schema_version=dataset_spec.schema_version,
        expected_case_count=dataset_spec.case_count,
    )
    calibration_cases, holdout_values = _calibration_cases(
        dataset,
        dataset_spec=dataset_spec,
    )
    probe = uuid4().hex
    trace_id = uuid4().hex
    engine = build_engine(database_url)
    factory = build_session_factory(engine)
    repository = SqlAlchemyCxContentRepository(factory)
    vector_repository = SqlAlchemyVectorIndexRepository(factory)
    store = ContentIngestionStore(content_repository=repository)
    document_ids: list[str] = []
    source_file_ids: list[str] = []
    vector_index_ids: list[str] = []
    retrieval_package_ids: list[str] = []
    checks: dict[str, bool] = {}
    samples: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {}
    candidate_diagnostics: dict[str, Any] = {}
    candidate_feature_samples: list[dict[str, Any]] = []
    repeat_runs: list[dict[str, Any]] = []
    binding: dict[str, str] | None = None
    provider_observation: dict[str, Any] = {}
    request_counts: dict[str, int] = {}
    try:
        with tempfile.TemporaryDirectory(
            prefix=f"nex-cx-{dataset_spec.request_prefix}-live-"
        ) as temp_dir:
            root = Path(temp_dir)
            storage = s136._storage_config(root)
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
            guarded_requester, request_counts = _holdout_guarded_requester(
                requester,
                holdout_values=holdout_values,
                environ=runtime_environ,
            )
            mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
            register_mock_provider_routes(mo_app)
            with (
                patched_environ(runtime_environ),
                patched_remote_request(guarded_requester),
            ):
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
                    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
                    register_retrieval_routes(
                        app,
                        store=store,
                        hybrid_runtime=composition.hybrid_retrieval_runtime,
                    )
                    with TestClient(app) as client:
                        seeded_cases = _seed_calibration_corpus(
                            cases=calibration_cases,
                            composition=composition,
                            store=store,
                            storage=storage,
                            probe=probe,
                            trace_id=trace_id,
                            document_ids=document_ids,
                            source_file_ids=source_file_ids,
                            vector_index_ids=vector_index_ids,
                            request_prefix=dataset_spec.request_prefix,
                        )
                        candidate_observations: list[dict[str, Any]] = []
                        for repeat_index in range(repeat_count):
                            run_samples, run_observations, run_binding = (
                                _retrieve_seeded_calibration_samples(
                                    seeded_cases=seeded_cases,
                                    client=client,
                                    runtime_environ=runtime_environ,
                                    probe=probe,
                                    trace_id=trace_id,
                                    repeat_index=repeat_index,
                                    retrieval_package_ids=retrieval_package_ids,
                                    request_prefix=dataset_spec.request_prefix,
                                )
                            )
                            if binding is None:
                                binding = run_binding
                            elif binding != run_binding:
                                raise ValueError(
                                    "multi-signal feature binding drifted"
                                )
                            repeat_runs.append(
                                _repeat_run_projection(
                                    repeat_index=repeat_index,
                                    samples=run_samples,
                                    observations=run_observations,
                                )
                            )
                            if repeat_index == 0:
                                samples = run_samples
                                candidate_observations = run_observations
                        diagnostics = (
                            diagnose_mixed_candidate_feature_discriminativeness(
                                samples,
                                dataset_id=str(admitted["dataset_id"]),
                                dataset_sha256=str(admitted["dataset_sha256"]),
                                expected_binding=binding,
                            )
                        )
                        candidate_diagnostics = diagnose_candidate_feature_correction(
                            candidate_observations,
                            dataset_id=str(admitted["dataset_id"]),
                            dataset_sha256=str(admitted["dataset_sha256"]),
                            expected_binding=binding,
                        )
                        candidate_feature_samples = (
                            build_candidate_feature_calibration_samples(
                                candidate_observations
                            )
                        )
                        telemetry = read_provider_telemetry(
                            mo_test_client,
                            trace_id,
                            f"{dataset_spec.request_prefix}-telemetry-{probe}",
                        )
            provider_observation = s136._provider_observation(telemetry)
            persisted = [
                s136._read_persisted_result(engine, package_id)
                for package_id in retrieval_package_ids
            ]
            restart_engine = build_engine(database_url)
            try:
                restart_persisted = [
                    s136._read_persisted_result(restart_engine, package_id)
                    for package_id in retrieval_package_ids
                ]
                restart_identity = s136._database_identity(restart_engine)
            finally:
                restart_engine.dispose()

            expected_models = {
                "embedding": runtime_environ["NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION"],
                "reranking": runtime_environ["NEX_MO_REMOTE_RERANKER_MODEL_REVISION"],
            }
            checks.update(
                {
                    "test_database_identity": s136._database_identity(engine)
                    == {"database": EXPECTED_DATABASE, "role": EXPECTED_ROLE},
                    "calibration_partition_only": (
                        len(calibration_cases)
                        == dataset_spec.calibration_package_count
                        and all(
                            case["partition"] == CALIBRATION_PARTITION
                            for case in calibration_cases
                        )
                    ),
                    "mixed_package_collection_complete": (
                        len(samples) == dataset_spec.calibration_package_count
                        and len(document_ids)
                        == dataset_spec.calibration_candidate_count
                        and all(
                            sample.get("retrieval_scope", {}).get(
                                "single_mixed_candidate_retrieval"
                            )
                            is True
                            and sample.get("retrieval_scope", {}).get(
                                "label_filtered_retrieval"
                            )
                            is False
                            and sample.get("feature_package", {})
                            .get("features", {})
                            .get("candidate_count")
                            == 4
                            for sample in samples
                        )
                    ),
                    "calibration_pairing_complete": (
                        len(
                            {
                                sample["sample_id"].rpartition(":")[0]
                                for sample in samples
                            }
                        )
                        == dataset_spec.calibration_scenario_count
                        and sum(bool(sample["expected_ready"]) for sample in samples)
                        == dataset_spec.calibration_scenario_count
                    ),
                    "holdout_provider_guard_active": (
                        request_counts.get("total", 0) > 0
                        and request_counts.get("holdout_blocked", 0) == 0
                    ),
                    "holdout_remained_sealed": (
                        diagnostics.get("holdout_access_permitted") is False
                        and diagnostics.get("dataset", {}).get("partition")
                        == CALIBRATION_PARTITION
                    ),
                    "diagnostics_only_no_policy_selection": (
                        diagnostics.get("status") == "DIAGNOSED"
                        and diagnostics.get("runtime_activation_permitted") is False
                        and diagnostics.get("threshold_selection_permitted") is False
                        and diagnostics.get("weight_selection_permitted") is False
                    ),
                    "candidate_diagnostics_complete": (
                        candidate_diagnostics.get("status") == "DIAGNOSED"
                        and candidate_diagnostics.get("dataset", {}).get(
                            "candidate_observation_count"
                        )
                        == dataset_spec.calibration_candidate_count
                        and candidate_diagnostics.get("dataset", {}).get(
                            "package_count"
                        )
                        == dataset_spec.calibration_package_count
                    ),
                    "candidate_feature_projection_complete": (
                        len(candidate_feature_samples)
                        == dataset_spec.calibration_package_count
                        and len(
                            {
                                sample["sample_id"].rpartition(":")[0]
                                for sample in candidate_feature_samples
                            }
                        )
                        == dataset_spec.calibration_scenario_count
                    ),
                    "candidate_diagnostics_only_no_policy_selection": (
                        candidate_diagnostics.get("runtime_activation_permitted")
                        is False
                        and candidate_diagnostics.get("feature_selection_permitted")
                        is False
                        and candidate_diagnostics.get("weight_selection_permitted")
                        is False
                        and candidate_diagnostics.get("threshold_selection_permitted")
                        is False
                        and candidate_diagnostics.get("holdout_access_permitted")
                        is False
                    ),
                    "immutable_provider_binding": (
                        binding is not None
                        and binding.get("embedding_model_revision")
                        == expected_models["embedding"]
                        and binding.get("reranker_model_revision")
                        == expected_models["reranking"]
                    ),
                    "provider_models_exact": all(
                        provider_observation.get(capability, {}).get("model") == model
                        for capability, model in expected_models.items()
                    ),
                    "provider_calls_complete": (
                        provider_observation.get("embedding", {}).get(
                            "success_count", 0
                        )
                        >= dataset_spec.calibration_candidate_count
                        + dataset_spec.calibration_package_count * repeat_count
                        and provider_observation.get("reranking", {}).get(
                            "success_count", 0
                        )
                        >= dataset_spec.calibration_package_count * repeat_count
                        and all(
                            provider_observation.get(capability, {}).get(
                                "failure_count", 0
                            )
                            == 0
                            for capability in ("embedding", "reranking")
                        )
                    ),
                    "postgres_packages_hash_only": (
                        len(persisted)
                        == len(retrieval_package_ids)
                        and dataset_spec.calibration_package_count
                        <= len(retrieval_package_ids)
                        <= dataset_spec.calibration_package_count * repeat_count
                        and all(
                            row.get("query_text_sha256")
                            and row.get("query_text_preview") is None
                            and row.get("evidence_count") == 4
                            for row in persisted
                        )
                    ),
                    "restart_readback_exact": (
                        restart_identity
                        == {"database": EXPECTED_DATABASE, "role": EXPECTED_ROLE}
                        and restart_persisted == persisted
                    ),
                    "repeat_collection_complete": (
                        len(repeat_runs) == repeat_count
                        and all(
                            run.get("sample_count")
                            == dataset_spec.calibration_package_count
                            and run.get("candidate_observation_count")
                            == dataset_spec.calibration_candidate_count
                            for run in repeat_runs
                        )
                    ),
                }
            )
    finally:
        s136._cleanup(
            engine,
            trace_id=trace_id,
            retrieval_package_ids=retrieval_package_ids,
            vector_index_ids=vector_index_ids,
            document_ids=document_ids,
            source_file_ids=source_file_ids,
        )
        checks["cleanup_complete"] = s136._cleanup_complete(
            engine,
            retrieval_package_ids=retrieval_package_ids,
            vector_index_ids=vector_index_ids,
            document_ids=document_ids,
            source_file_ids=source_file_ids,
        )
        engine.dispose()

    return {
        "database_identity": {"database": EXPECTED_DATABASE, "role": EXPECTED_ROLE},
        "dataset": {
            "dataset_id": admitted["dataset_id"],
            "dataset_sha256": admitted["dataset_sha256"],
            "partition": CALIBRATION_PARTITION,
            "scenario_count": dataset_spec.calibration_scenario_count,
            "package_count": dataset_spec.calibration_package_count,
            "candidate_count": dataset_spec.calibration_candidate_count,
            "holdout_status": "SEALED_NOT_COLLECTED",
        },
        "binding": binding,
        "provider_observation": provider_observation,
        "provider_request_counts": request_counts,
        "collection": {
            "sample_count": len(samples),
            "ready_count": sum(bool(sample["expected_ready"]) for sample in samples),
            "low_confidence_count": sum(
                not bool(sample["expected_ready"]) for sample in samples
            ),
            "sample_set_hash": semantic_sha256_hash_ref(
                sorted(str(sample["sample_hash"]) for sample in samples)
            ),
            "samples": sorted(samples, key=lambda sample: str(sample["sample_id"])),
            "candidate_feature_samples": candidate_feature_samples,
        },
        "feature_diagnostics": diagnostics,
        "candidate_feature_diagnostics": candidate_diagnostics,
        "repeat_collection": {
            "repeat_count": repeat_count,
            "retrieval_request_count": (
                dataset_spec.calibration_package_count * repeat_count
            ),
            "candidate_observation_count": (
                dataset_spec.calibration_candidate_count * repeat_count
            ),
            "runs": repeat_runs,
        },
        "persistence": {
            "retrieval_package_count": len(retrieval_package_ids),
            "document_count": len(document_ids),
            "raw_query_persisted": False,
            "raw_content_persisted_in_evidence": False,
        },
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _collect_calibration_samples(  # pragma: no cover - PostgreSQL/DGX protected
    *,
    cases: Sequence[Mapping[str, Any]],
    client: TestClient,
    composition: Any,
    store: ContentIngestionStore,
    storage: Any,
    runtime_environ: Mapping[str, str],
    probe: str,
    trace_id: str,
    document_ids: list[str],
    source_file_ids: list[str],
    vector_index_ids: list[str],
    retrieval_package_ids: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    seeded_cases = _seed_calibration_corpus(
        cases=cases,
        composition=composition,
        store=store,
        storage=storage,
        probe=probe,
        trace_id=trace_id,
        document_ids=document_ids,
        source_file_ids=source_file_ids,
        vector_index_ids=vector_index_ids,
    )
    return _retrieve_seeded_calibration_samples(
        seeded_cases=seeded_cases,
        client=client,
        runtime_environ=runtime_environ,
        probe=probe,
        trace_id=trace_id,
        repeat_index=0,
        retrieval_package_ids=retrieval_package_ids,
    )


def _seed_calibration_corpus(  # pragma: no cover - PostgreSQL/DGX protected
    *,
    cases: Sequence[Mapping[str, Any]],
    composition: Any,
    store: ContentIngestionStore,
    storage: Any,
    probe: str,
    trace_id: str,
    document_ids: list[str],
    source_file_ids: list[str],
    vector_index_ids: list[str],
    request_prefix: str = "s20qe",
) -> list[dict[str, Any]]:
    seeded_cases: list[dict[str, Any]] = []
    for case in cases:
        document_to_candidate: dict[str, str] = {}
        for candidate in case["candidates"]:
            indexed = s136._ingest_document(
                probe=probe,
                label=(
                    f"{request_prefix}-{case['case_id']}-"
                    f"{candidate['candidate_id']}"
                ),
                source_text=str(candidate["text"]),
                request_id=(
                    f"{request_prefix}-index-{case['case_id']}-"
                    f"{candidate['candidate_id']}"
                ),
                trace_id=trace_id,
                store=store,
                storage=storage,
            )
            document_id = indexed["document_id"]
            document_ids.append(document_id)
            source_file_ids.append(indexed["source_file_id"])
            document_to_candidate[document_id] = str(candidate["candidate_id"])
            index_result = composition.ingestion_vector_indexer(
                {
                    "document_id": document_id,
                    "job_id": indexed["job_id"],
                    "idempotency_key": indexed["upload_id"],
                    "tenant_ref": {"type": "oa.tenant", "id": TENANT_ID},
                    "owner_subject_ref": {"type": "oa.user", "id": OWNER_ID},
                    "request_id": (
                        f"{request_prefix}-index-{case['case_id']}-"
                        f"{candidate['candidate_id']}"
                    ),
                    "trace_id": trace_id,
                    "created_at": indexed["created_at"],
                    "updated_at": indexed["updated_at"],
                }
            )
            vector_index_ids.append(index_result.output_ref.split(":", 1)[1])
        seeded_cases.append(
            {
                "case": case,
                "document_to_candidate": document_to_candidate,
            }
        )
    return seeded_cases


def _retrieve_seeded_calibration_samples(  # pragma: no cover - protected live
    *,
    seeded_cases: Sequence[Mapping[str, Any]],
    client: TestClient,
    runtime_environ: Mapping[str, str],
    probe: str,
    trace_id: str,
    repeat_index: int,
    retrieval_package_ids: list[str],
    request_prefix: str = "s20qe",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    samples: list[dict[str, Any]] = []
    candidate_observations: list[dict[str, Any]] = []
    stable_binding: dict[str, str] | None = None
    for seeded in seeded_cases:
        case = seeded["case"]
        document_to_candidate = seeded["document_to_candidate"]
        if not isinstance(case, Mapping) or not isinstance(
            document_to_candidate, Mapping
        ):
            raise TypeError("seeded calibration case is invalid")

        response = _retrieve_scope(
            client,
            query=str(case["query"]),
            document_ids=list(document_to_candidate),
            request_id=(
                f"{request_prefix}-calibration-r{repeat_index}-"
                f"{case['case_id']}-{probe}"
            ),
            trace_id=trace_id,
        )
        if response.status_code != 200:
            raise ValueError("mixed-candidate retrieval request failed")
        package = response.json()
        package_id = _required_string(
            package.get("retrieval_package_id"), "retrieval_package_id"
        )
        if package_id not in retrieval_package_ids:
            retrieval_package_ids.append(package_id)
        observed_binding = _feature_binding(package, runtime_environ)
        if stable_binding is None:
            stable_binding = observed_binding
        elif observed_binding != stable_binding:
            raise ValueError("multi-signal feature binding drifted")
        numeric_evidence = _numeric_mixed_evidence(package, document_to_candidate)
        samples.append(
            build_mixed_candidate_calibration_sample(
                case,
                numeric_evidence,
                binding=stable_binding,
            )
        )
        candidate_observations.extend(
            build_candidate_diagnostic_observations(case, numeric_evidence)
        )
    if stable_binding is None:
        raise ValueError("multi-signal feature binding is unavailable")
    return samples, candidate_observations, stable_binding


def _repeat_run_projection(
    *,
    repeat_index: int,
    samples: Sequence[Mapping[str, Any]],
    observations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    projected = {
        "repeat_index": repeat_index,
        "sample_count": len(samples),
        "candidate_observation_count": len(observations),
        "sample_set_hash": semantic_sha256_hash_ref(
            sorted(str(sample["sample_hash"]) for sample in samples)
        ),
        "observation_set_hash": semantic_sha256_hash_ref(
            sorted(str(row["observation_hash"]) for row in observations)
        ),
        "candidate_observations": sorted(
            (dict(row) for row in observations),
            key=lambda row: (str(row["sample_id"]), int(row["rank"])),
        ),
    }
    projected["run_hash"] = semantic_sha256_hash_ref(projected)
    return projected


def _repeat_count(value: object) -> int:
    if isinstance(value, bool):
        raise TypeError("repeat count is invalid")
    try:
        count = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError("repeat count is invalid") from exc
    if str(value).strip() != str(count) or not 1 <= count <= 5:
        raise ValueError("repeat count is invalid")
    return count


def _load_dataset(
    path: Path,
    *,
    schema_version: str = V3_DATASET_SPEC.schema_version,
    expected_case_count: int = V3_DATASET_SPEC.case_count,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("dataset_schema_version") != schema_version
        or not isinstance(payload.get("dataset_id"), str)
        or not isinstance(payload.get("cases"), list)
        or len(payload["cases"]) != expected_case_count
    ):
        raise ValueError("calibration dataset is invalid")
    return payload


def _calibration_cases(
    dataset: Mapping[str, Any],
    *,
    dataset_spec: LiveCalibrationDatasetSpec = V3_DATASET_SPEC,
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    calibration: list[dict[str, Any]] = []
    holdout_values: list[str] = []
    scenario_partitions: dict[str, str] = {}
    for value in dataset.get("cases", []):
        if not isinstance(value, Mapping):
            raise TypeError("v3 calibration case is invalid")
        partition = value.get("partition")
        scenario_id = _required_string(value.get("scenario_id"), "scenario_id")
        if partition not in {CALIBRATION_PARTITION, HOLDOUT_PARTITION}:
            raise ValueError("v3 calibration partition is invalid")
        previous = scenario_partitions.setdefault(scenario_id, str(partition))
        if previous != partition:
            raise ValueError("v3 scenario pair crossed partitions")
        if partition == CALIBRATION_PARTITION:
            calibration.append(dict(value))
        else:
            holdout_values.append(_required_string(value.get("query"), "query"))
            candidates = value.get("candidates")
            if not isinstance(candidates, list):
                raise ValueError("v3 holdout candidates are invalid")
            holdout_values.extend(
                _required_string(candidate.get("text"), "candidate.text")
                for candidate in candidates
                if isinstance(candidate, Mapping)
            )
            if len(candidates) != 4:
                raise ValueError("v3 holdout candidates are invalid")
    calibration_scenarios = {case["scenario_id"] for case in calibration}
    holdout_scenarios = {
        scenario
        for scenario, partition in scenario_partitions.items()
        if partition == HOLDOUT_PARTITION
    }
    if (
        len(calibration) != dataset_spec.calibration_package_count
        or len(calibration_scenarios) != dataset_spec.calibration_scenario_count
        or len(holdout_scenarios) != dataset_spec.holdout_scenario_count
        or len(holdout_values) != dataset_spec.holdout_protected_value_count
    ):
        raise ValueError("calibration dataset partitions are invalid")
    return sorted(calibration, key=lambda case: str(case["case_id"])), tuple(
        holdout_values
    )


def _holdout_guarded_requester(
    requester: HttpRequester | None,
    *,
    holdout_values: Sequence[str],
    environ: Mapping[str, str],
) -> tuple[HttpRequester, dict[str, int]]:
    base = requester or remote_provider.httpx.request
    counts = {"total": 0, "embedding": 0, "reranking": 0, "holdout_blocked": 0}
    embedding_url = str(environ.get("NEX_MO_REMOTE_EMBEDDING_URL", ""))
    reranker_url = str(environ.get("NEX_MO_REMOTE_RERANKER_URL", ""))

    def guarded(method: str, url: str, **kwargs: Any) -> Any:
        serialized = json.dumps(kwargs.get("json"), ensure_ascii=False, sort_keys=True)
        if any(value in serialized for value in holdout_values):
            counts["holdout_blocked"] += 1
            raise ValueError("holdout content reached a provider request")
        counts["total"] += 1
        if url == embedding_url:
            counts["embedding"] += 1
        elif url == reranker_url:
            counts["reranking"] += 1
        return base(method, url, **kwargs)

    return guarded, counts


def _numeric_mixed_evidence(
    package: Mapping[str, Any],
    document_to_candidate: Mapping[str, str],
) -> list[dict[str, Any]]:
    items = package.get("evidence_items")
    if not isinstance(items, list) or len(items) != 4:
        raise ValueError("exactly four mixed evidence candidates are required")
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping) or not isinstance(item.get("scores"), Mapping):
            raise TypeError("retrieval evidence score package is invalid")
        document_id = item.get("content_object_id")
        candidate_id = document_to_candidate.get(str(document_id))
        if candidate_id is None:
            raise ValueError("retrieval evidence escaped the admitted candidate scope")
        result.append(
            {
                "candidate_id": candidate_id,
                "rank": item.get("rank"),
                "scores": dict(item["scores"]),
            }
        )
    return result


def _feature_binding(
    package: Mapping[str, Any],
    runtime_environ: Mapping[str, str],
) -> dict[str, str]:
    profile = _mapping(package.get("retrieval_profile"))
    embedding = _mapping(profile.get("embedding_profile"))
    reranker = _mapping(profile.get("reranker_profile"))
    quality = _mapping(profile.get("quality_policy"))
    tokenizer = _mapping(profile.get("bm25_tokenizer_profile"))
    if (
        embedding.get("model_revision")
        != runtime_environ.get("NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION")
        or reranker.get("model_revision")
        != runtime_environ.get("NEX_MO_REMOTE_RERANKER_MODEL_REVISION")
        or not tokenizer
    ):
        raise ValueError("live provider or tokenizer binding drifted")
    return {
        "embedding_model_revision": _required_string(
            runtime_environ.get("NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION"),
            "embedding_model_revision",
        ),
        "reranker_model_revision": _required_string(
            runtime_environ.get("NEX_MO_REMOTE_RERANKER_MODEL_REVISION"),
            "reranker_model_revision",
        ),
        "ranking_policy_id": _required_string(
            quality.get("policy_id"), "ranking_policy_id"
        ),
        "tokenizer_policy_id": (
            TOKENIZER_POLICY_PREFIX + semantic_sha256_hash_ref(tokenizer)
        ),
        "chunk_policy_id": _required_string(
            profile.get("chunk_policy"), "chunk_policy_id"
        ),
    }


def _retrieve_scope(
    client: TestClient,
    *,
    query: str,
    document_ids: Sequence[str],
    request_id: str,
    trace_id: str,
) -> Any:
    return client.post(
        "/api/v1/retrieval/context",
        json={
            "query_text": query,
            "document_scope": {"document_ids": list(document_ids)},
            "top_k": 4,
            "purpose": "confidence_probe",
        },
        headers=s136._headers(request_id, trace_id, OWNER_ID),
    )


def _configuration_issues(environ: Mapping[str, str]) -> list[dict[str, str]]:
    required = (
        *PROTECTED_ENV_KEYS,
        "NEX_MO_REMOTE_EMBEDDING_MODEL",
        "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION",
        "NEX_MO_REMOTE_RERANKER_MODEL",
        "NEX_MO_REMOTE_RERANKER_MODEL_REVISION",
    )
    issues = [
        {"error_code": "configuration_missing", "field": key}
        for key in required
        if not str(environ.get(key, "")).strip()
    ]
    expected = {
        "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "openai_embeddings",
        "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE": "rerank",
    }
    issues.extend(
        {"error_code": "configuration_mismatch", "field": key}
        for key, value in expected.items()
        if str(environ.get(key, "")).strip() != value
    )
    return issues


def _assert_redacted(evidence: object, environ: Mapping[str, str]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    dataset = _load_dataset(DEFAULT_V3_PATH)
    protected = [
        *(str(case["query"]) for case in dataset["cases"]),
        *(
            str(candidate["text"])
            for case in dataset["cases"]
            for candidate in case["candidates"]
        ),
        *(str(environ.get(key, "")) for key in PROTECTED_ENV_KEYS if environ.get(key)),
    ]
    if any(len(value) >= 4 and value in serialized for value in protected):
        raise ValueError("S20Q-E evidence contains protected data")


def _failure(
    failure_code: str,
    *,
    detail: object | None = None,
    execution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": failure_code,
    }
    if detail is not None:
        result["detail"] = detail
    if execution is not None:
        result["execution"] = dict(execution)
    return result


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is invalid")
    return value.strip()


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        collection = _mapping(result.get("collection"))
        diagnostics = _mapping(result.get("feature_diagnostics"))
        return (
            "gb2_s20qe_v3_calibration_collection=pass "
            f"samples={collection.get('sample_count')} "
            f"diagnostics={diagnostics.get('status')} holdout=sealed"
        )
    if status == "skipped":
        return "gb2_s20qe_v3_calibration_collection=skipped"
    return (
        "gb2_s20qe_v3_calibration_collection=fail "
        f"error={result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qe_v3_calibration_collection()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            f"{json.dumps(result, indent=2, sort_keys=True)}\n",
            encoding="utf-8",
        )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
