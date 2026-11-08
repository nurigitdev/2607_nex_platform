#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
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
    DEFAULT_V2_PATH,
    admit_calibration_dataset_files,
)
from nex_cx.embedding_index import DEFAULT_EMBEDDING_ALIAS
from nex_cx.ingestion import ContentIngestionStore
from nex_cx.mvp_runtime import build_cx_mvp_runtime
from nex_cx.pgvector_store import build_pgvector_cx_vector_store
from nex_cx.private_text_store import FileSystemCxPrivateTextStore
from nex_cx.repository import SqlAlchemyCxContentRepository
from nex_cx.retrieval import (
    DEFAULT_RERANKER_ALIAS,
    register_retrieval_routes,
)
from nex_cx.retrieval_confidence_feature_audit import (
    audit_multisignal_feature_discriminativeness,
)
from nex_cx.retrieval_confidence_multisignal import (
    build_admitted_multisignal_profile,
    build_multisignal_feature_package,
    decide_multisignal_confidence,
)
from nex_cx.retrieval_confidence_weight_selection import (
    MultiSignalWeightSelectionConstraints,
    apply_multisignal_weights,
    select_multisignal_calibration_weights,
)
from nex_cx.vector_index_repository import (
    SqlAlchemyVectorIndexRepository,
)
from nex_mo import remote_provider
from nex_mo.providers import register_mock_provider_routes
from nex_runtime import (
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    evaluate_binary_score_threshold,
    issue_mock_service_token,
    redact_database_url,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_migrations import (
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)
from run_protected_dgx_live_profile import (
    protected_dgx_vllm_profile_defaults,
)
from run_protected_live_rag_smoke import (
    InProcessLiveMoClient,
    patched_environ,
    patched_remote_request,
    read_provider_telemetry,
)

SCHEMA_VERSION = "gb2_s20q_multisignal_live_holdout.v1"
SMOKE_ENV = "NEX_GB2_S20Q_MULTISIGNAL_LIVE_HOLDOUT"
PROFILE_ENV = "NEX_GB2_S20Q_PROFILE"
AUDIT_ONLY_ENV = "NEX_GB2_S20Q_FEATURE_AUDIT_ONLY"
SERVICE_ID = "nex-cx"
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"
TENANT_ID = s136.TENANT_ID
OWNER_ID = s136.OWNER_ID
CALIBRATION_PARTITION = "CALIBRATION"
HOLDOUT_PARTITION = "HOLDOUT"
TOKENIZER_POLICY_PREFIX = "cx-tokenizer-profile:"
PROTECTED_ENV_KEYS = (
    "NEX_CX_TEST_DATABASE_URL",
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
)

HttpRequester = Callable[..., Any]
SmokeExecutor = Callable[..., dict[str, Any]]


def run_gb2_s20q_multisignal_live_holdout(
    environ: Mapping[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
    executor: SmokeExecutor | None = None,
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
        execute = executor or _execute_live_acceptance
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
            "live_acceptance_failed",
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


def _execute_live_acceptance(  # pragma: no cover - PostgreSQL/DGX protected
    *,
    database_url: str,
    database_env: str,
    runtime_environ: dict[str, str],
    requester: HttpRequester | None,
) -> dict[str, Any]:
    audit_only = runtime_environ.get(AUDIT_ONLY_ENV) == "1"
    admitted = admit_calibration_dataset_files()
    dataset = _load_dataset(DEFAULT_V2_PATH)
    partitions = _partition_cases(dataset)
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
    provider_observation: dict[str, Any] = {}
    feature_audit: dict[str, Any] = {}
    weight_selection_result: dict[str, Any] = {}
    unrestricted_diagnostic: dict[str, Any] = {}
    calibration_result: dict[str, Any] = {}
    holdout_evaluation: dict[str, Any] = {}
    profile: dict[str, Any] | None = None
    freeze_record: dict[str, Any] = {}
    calibration_samples: list[dict[str, Any]] = []
    holdout_samples: list[dict[str, Any]] = []
    binding: dict[str, str] | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="nex-cx-s20q-live-") as temp_dir:
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
            mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
            register_mock_provider_routes(mo_app)
            with (
                patched_environ(runtime_environ),
                patched_remote_request(requester),
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
                        calibration_samples, binding = _collect_partition(
                            cases=partitions[CALIBRATION_PARTITION],
                            partition=CALIBRATION_PARTITION,
                            client=client,
                            composition=composition,
                            store=store,
                            storage=storage,
                            runtime_environ=runtime_environ,
                            probe=probe,
                            trace_id=trace_id,
                            document_ids=document_ids,
                            source_file_ids=source_file_ids,
                            vector_index_ids=vector_index_ids,
                            retrieval_package_ids=retrieval_package_ids,
                            expected_binding=None,
                        )
                        feature_audit = audit_multisignal_feature_discriminativeness(
                            calibration_samples,
                            dataset_id=str(admitted["v2"]["dataset_id"]),
                            dataset_sha256=str(admitted["v2"]["dataset_sha256"]),
                            expected_binding=binding,
                        )
                        weight_selection_result = (
                            select_multisignal_calibration_weights(
                                calibration_samples,
                                dataset_id=str(admitted["v2"]["dataset_id"]),
                                dataset_sha256=str(admitted["v2"]["dataset_sha256"]),
                                expected_binding=binding,
                            )
                        )
                        unrestricted_diagnostic = (
                            select_multisignal_calibration_weights(
                                calibration_samples,
                                dataset_id=(
                                    f"{admitted['v2']['dataset_id']}:"
                                    "unrestricted-diagnostic"
                                ),
                                dataset_sha256=str(admitted["v2"]["dataset_sha256"]),
                                expected_binding=binding,
                                constraints=MultiSignalWeightSelectionConstraints(
                                    minimum_feature_weight=0.0,
                                    maximum_feature_weight=1.0,
                                    minimum_reranker_weight=0.0,
                                    minimum_retrieval_weight=0.0,
                                ),
                            )
                        )
                        selected = _mapping(weight_selection_result.get("selected"))
                        if weight_selection_result.get("status") == "SELECTED":
                            selected_weights = _mapping(selected.get("weights"))
                            calibration_samples = apply_multisignal_weights(
                                calibration_samples,
                                weights=selected_weights,
                            )
                            calibration_result = dict(
                                _mapping(selected.get("calibration"))
                            )
                            if not audit_only:
                                freeze_record = _freeze_calibration(
                                    calibration_result,
                                    weight_selection_hash=str(
                                        weight_selection_result["selection_hash"]
                                    ),
                                )
                                holdout_samples, holdout_binding = _collect_partition(
                                    cases=partitions[HOLDOUT_PARTITION],
                                    partition=HOLDOUT_PARTITION,
                                    client=client,
                                    composition=composition,
                                    store=store,
                                    storage=storage,
                                    runtime_environ=runtime_environ,
                                    probe=probe,
                                    trace_id=trace_id,
                                    document_ids=document_ids,
                                    source_file_ids=source_file_ids,
                                    vector_index_ids=vector_index_ids,
                                    retrieval_package_ids=retrieval_package_ids,
                                    expected_binding=binding,
                                )
                                if holdout_binding != binding:
                                    raise ValueError("holdout binding drifted")
                                holdout_samples = apply_multisignal_weights(
                                    holdout_samples,
                                    weights=selected_weights,
                                )
                                holdout_evaluation = _evaluate_holdout(
                                    samples=holdout_samples,
                                    dataset_id=str(admitted["v2"]["dataset_id"]),
                                    threshold=float(freeze_record["threshold"]),
                                    expected_binding=binding,
                                )
                                if holdout_evaluation.get("status") == "PASSED":
                                    profile = build_admitted_multisignal_profile(
                                        profile_id=(
                                            "gb2-s20q-"
                                            f"{str(admitted['v2']['dataset_sha256'])[:12]}"
                                        ),
                                        version="0001",
                                        expected_binding=binding,
                                        dataset_id=str(admitted["v2"]["dataset_id"]),
                                        dataset_sha256=str(
                                            admitted["v2"]["dataset_sha256"]
                                        ),
                                        calibration_result=calibration_result,
                                        holdout_evaluation=holdout_evaluation,
                                    )
                        else:
                            calibration_result = dict(
                                _mapping(
                                    _mapping(
                                        weight_selection_result.get("best_effort")
                                    ).get("calibration")
                                )
                            )
                        telemetry = read_provider_telemetry(
                            mo_test_client,
                            trace_id,
                            f"s20q-telemetry-{probe}",
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

            calibration_passed = (
                weight_selection_result.get("status") == "SELECTED"
                and calibration_result.get("status") == "PASSED"
            )
            holdout_eligible = calibration_passed and not audit_only
            expected_models = {
                "embedding": runtime_environ["NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION"],
                "reranking": runtime_environ["NEX_MO_REMOTE_RERANKER_MODEL_REVISION"],
            }
            expected_document_count = 120 if holdout_eligible else 80
            expected_package_count = 60 if holdout_eligible else 40
            checks.update(
                {
                    "test_database_identity": s136._database_identity(engine)
                    == {"database": EXPECTED_DATABASE, "role": EXPECTED_ROLE},
                    "query_group_partitions_independent": not (
                        {case["case_id"] for case in partitions[CALIBRATION_PARTITION]}
                        & {case["case_id"] for case in partitions[HOLDOUT_PARTITION]}
                    ),
                    "calibration_partition_collected_complete": (
                        len(document_ids) >= 80
                        and len(calibration_samples) == 40
                        and len(retrieval_package_ids) >= 40
                    ),
                    "feature_discriminativeness_audited": (
                        feature_audit.get("status") == "AUDITED"
                        and feature_audit.get("runtime_activation_permitted") is False
                        and feature_audit.get("holdout_access_permitted") is False
                    ),
                    "unrestricted_search_diagnostic_only": (
                        not unrestricted_diagnostic
                        or unrestricted_diagnostic.get("runtime_activation_permitted")
                        is False
                    ),
                    "calibration_weight_selection_completed": (
                        weight_selection_result.get("status")
                        in {"SELECTED", "NO_ACCEPTABLE_WEIGHT_PROFILE"}
                    ),
                    "immutable_reranker_revision_bound": (
                        binding is not None
                        and binding.get("reranker_model_revision")
                        == runtime_environ["NEX_MO_REMOTE_RERANKER_MODEL_REVISION"]
                    ),
                    "provider_models_exact": all(
                        provider_observation.get(capability, {}).get("model") == model
                        for capability, model in expected_models.items()
                    ),
                    "provider_calls_complete": (
                        provider_observation.get("embedding", {}).get(
                            "success_count", 0
                        )
                        >= expected_document_count + expected_package_count
                        and provider_observation.get("reranking", {}).get(
                            "success_count", 0
                        )
                        >= expected_package_count
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
                        == expected_package_count
                        and all(
                            row.get("query_text_sha256")
                            and row.get("query_text_preview") is None
                            and row.get("evidence_count") == 2
                            for row in persisted
                        )
                    ),
                    "restart_readback_exact": (
                        restart_identity
                        == {"database": EXPECTED_DATABASE, "role": EXPECTED_ROLE}
                        and restart_persisted == persisted
                    ),
                }
            )
            if not audit_only:
                checks["calibration_weight_profile_selected"] = calibration_passed
            if holdout_eligible:
                checks.update(
                    {
                        "all_dataset_pairs_consumed_once": (
                            len(document_ids) == 120 and len(holdout_samples) == 20
                        ),
                        "calibration_threshold_frozen_before_holdout": (
                            freeze_record.get("status") == "FROZEN"
                            and bool(freeze_record.get("freeze_hash"))
                        ),
                        "holdout_threshold_not_reselected": (
                            holdout_evaluation.get("threshold")
                            == freeze_record.get("threshold")
                        ),
                        "holdout_passed": (
                            holdout_evaluation.get("status") == "PASSED"
                        ),
                        "active_profile_admitted": (
                            profile is not None
                            and profile.get("status") == "ACTIVE"
                            and profile.get("runtime_activation_permitted") is True
                        ),
                    }
                )
            else:
                checks.update(
                    {
                        "holdout_remained_sealed": (
                            not freeze_record
                            and not holdout_samples
                            and not holdout_evaluation
                        ),
                        "profile_remained_inactive": profile is None,
                        "audit_only_boundary_respected": (
                            not audit_only
                            or (
                                not freeze_record
                                and not holdout_samples
                                and not holdout_evaluation
                                and profile is None
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
            "dataset_id": admitted["v2"]["dataset_id"],
            "dataset_sha256": admitted["v2"]["dataset_sha256"],
            "calibration_query_group_count": 20,
            "holdout_query_group_count": 10,
            "pair_count": 120,
        },
        "provider_observation": provider_observation,
        "binding": binding,
        "feature_audit": feature_audit,
        "weight_selection": weight_selection_result,
        "unrestricted_diagnostic": unrestricted_diagnostic,
        "calibration": _evaluation_projection(calibration_result),
        "acceptance_phase": (
            "HOLDOUT_EVALUATED"
            if holdout_evaluation
            else (
                "CALIBRATION_AUDITED_HOLDOUT_SEALED"
                if audit_only
                else "WEIGHT_SELECTION_REJECTED_HOLDOUT_SEALED"
            )
        ),
        "freeze": freeze_record,
        "holdout": _holdout_projection(holdout_evaluation),
        "profile": _profile_projection(profile),
        "persistence": {
            "retrieval_package_count": len(retrieval_package_ids),
            "document_count": len(document_ids),
            "raw_query_persisted": False,
            "raw_document_text_persisted_in_evidence": False,
        },
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _collect_partition(  # pragma: no cover - PostgreSQL/DGX protected
    *,
    cases: Sequence[Mapping[str, Any]],
    partition: str,
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
    expected_binding: Mapping[str, str] | None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    samples: list[dict[str, Any]] = []
    stable_binding = dict(expected_binding) if expected_binding is not None else None
    for case in cases:
        case_documents: dict[bool, list[str]] = {True: [], False: []}
        for document in case["documents"]:
            indexed = s136._ingest_document(
                probe=probe,
                label=f"s20q-{case['case_id']}-{document['document_id']}",
                source_text=str(document["text"]),
                request_id=f"s20q-index-{case['case_id']}-{document['document_id']}",
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
                    "request_id": (
                        f"s20q-index-{case['case_id']}-{document['document_id']}"
                    ),
                    "trace_id": trace_id,
                    "created_at": indexed["created_at"],
                    "updated_at": indexed["updated_at"],
                }
            )
            vector_index_ids.append(index_result.output_ref.split(":", 1)[1])
            case_documents[bool(document["expected_ready"])].append(
                indexed["document_id"]
            )
        for expected_ready in (True, False):
            response = _retrieve_scope(
                client,
                query=str(case["query"]),
                document_ids=case_documents[expected_ready],
                request_id=(
                    f"s20q-{partition.lower()}-{case['case_id']}-"
                    f"{'ready' if expected_ready else 'low'}-{probe}"
                ),
                trace_id=trace_id,
            )
            if response.status_code != 200:
                raise ValueError("multi-signal retrieval request failed")
            package = response.json()
            package_id = package.get("retrieval_package_id")
            if not isinstance(package_id, str) or not package_id:
                raise ValueError("retrieval package identity is invalid")
            retrieval_package_ids.append(package_id)
            observed_binding = _feature_binding(package, runtime_environ)
            if stable_binding is None:
                stable_binding = observed_binding
            elif observed_binding != stable_binding:
                raise ValueError("multi-signal feature binding drifted")
            evidence = _numeric_evidence(package)
            feature_package = build_multisignal_feature_package(
                evidence,
                binding=stable_binding,
            )
            samples.append(
                {
                    "sample_id": (
                        f"{case['case_id']}:"
                        f"{'positive' if expected_ready else 'negative'}"
                    ),
                    "expected_ready": expected_ready,
                    "feature_package": feature_package,
                }
            )
    if stable_binding is None:
        raise ValueError("multi-signal feature binding is unavailable")
    return samples, stable_binding


def _load_dataset(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("dataset_schema_version") != "model_calibration_dataset.v2"
        or not isinstance(payload.get("dataset_id"), str)
        or not isinstance(payload.get("cases"), list)
        or len(payload["cases"]) != 30
    ):
        raise ValueError("multi-signal dataset is invalid")
    return payload


def _partition_cases(dataset: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    partitions = {CALIBRATION_PARTITION: [], HOLDOUT_PARTITION: []}
    seen: set[str] = set()
    for case in dataset.get("cases", []):
        if not isinstance(case, Mapping):
            raise ValueError(  # noqa: TRY004 - dataset contract violation
                "multi-signal dataset case is invalid"
            )
        case_id = case.get("case_id")
        partition = case.get("partition")
        documents = case.get("documents")
        if (
            not isinstance(case_id, str)
            or not case_id
            or case_id in seen
            or partition not in partitions
            or not isinstance(case.get("query"), str)
            or not case["query"]
            or not isinstance(documents, list)
            or len(documents) != 4
        ):
            raise ValueError("multi-signal dataset case is invalid")
        ready_values = [
            document.get("expected_ready")
            for document in documents
            if isinstance(document, Mapping)
        ]
        if (
            len(ready_values) != 4
            or ready_values.count(True) != 2
            or ready_values.count(False) != 2
            or any(
                not isinstance(document.get("document_id"), str)
                or not isinstance(document.get("text"), str)
                or not document["text"]
                for document in documents
            )
        ):
            raise ValueError("multi-signal dataset labels are invalid")
        seen.add(case_id)
        partitions[str(partition)].append(dict(case))
    if (
        len(partitions[CALIBRATION_PARTITION]) != 20
        or len(partitions[HOLDOUT_PARTITION]) != 10
    ):
        raise ValueError("multi-signal dataset partitions are invalid")
    return partitions


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


def _numeric_evidence(package: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = package.get("evidence_items")
    if not isinstance(items, list) or len(items) != 2:
        raise ValueError("exactly two admitted evidence candidates are required")
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping) or not isinstance(item.get("scores"), Mapping):
            raise ValueError(  # noqa: TRY004 - evidence contract violation
                "retrieval evidence score package is invalid"
            )
        result.append({"rank": item.get("rank"), "scores": dict(item["scores"])})
    return result


def _freeze_calibration(
    calibration_result: Mapping[str, Any],
    *,
    weight_selection_hash: str | None = None,
) -> dict[str, Any]:
    evaluation = _mapping(calibration_result.get("evaluation"))
    if calibration_result.get("status") != "PASSED":
        raise ValueError("multi-signal calibration did not pass")
    freeze = {
        "status": "FROZEN",
        "threshold": evaluation.get("selected_threshold"),
        "calibration_evaluation_hash": calibration_result.get("evaluation_hash"),
        "feature_package_set_hash": calibration_result.get("feature_package_set_hash"),
        "selection_partition": CALIBRATION_PARTITION,
        "threshold_reselection_allowed": False,
    }
    if weight_selection_hash is not None:
        freeze["weight_selection_hash"] = _required_string(
            weight_selection_hash,
            "weight_selection_hash",
        )
        freeze["weights"] = dict(_mapping(calibration_result.get("weights")))
    freeze["freeze_hash"] = semantic_sha256_hash_ref(freeze)
    return freeze


def _evaluate_holdout(
    *,
    samples: Sequence[Mapping[str, Any]],
    dataset_id: str,
    threshold: float,
    expected_binding: Mapping[str, Any],
) -> dict[str, Any]:
    scored: list[dict[str, Any]] = []
    for sample in samples:
        package = _mapping(sample.get("feature_package"))
        decision = decide_multisignal_confidence(
            package,
            expected_binding=expected_binding,
            threshold=threshold,
        )
        if decision.get("status") not in {"READY", "LOW_CONFIDENCE"}:
            raise ValueError("holdout feature package is incomplete")
        scored.append(
            {
                "sample_id": sample.get("sample_id"),
                "expected_ready": sample.get("expected_ready"),
                "score": decision.get("score"),
            }
        )
    return evaluate_binary_score_threshold(
        scored,
        dataset_id=f"{dataset_id}:holdout",
        threshold=threshold,
    )


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
            "top_k": 2,
            "purpose": "confidence_probe",
        },
        headers=_headers(request_id, trace_id),
    )


def _headers(request_id: str, trace_id: str) -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ae-api",
        audience=SERVICE_ID,
    ).access_token
    return {
        "Authorization": f"Bearer {token}",
        "X-NEX-Tenant-ID": TENANT_ID,
        "X-NEX-Subject-ID": OWNER_ID,
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _evaluation_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    evaluation = _mapping(result.get("evaluation"))
    return {
        "status": result.get("status"),
        "reason_code": result.get("reason_code"),
        "sample_count": evaluation.get("sample_count"),
        "positive_count": evaluation.get("positive_count"),
        "negative_count": evaluation.get("negative_count"),
        "selected_threshold": evaluation.get("selected_threshold"),
        "selected_metrics": evaluation.get("selected_metrics"),
        "best_effort_metrics": evaluation.get("best_effort_metrics"),
        "candidate_count": evaluation.get("candidate_count"),
        "score_distribution": evaluation.get("score_distribution"),
        "evaluation_hash": result.get("evaluation_hash"),
    }


def _holdout_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status"),
        "sample_count": result.get("sample_count"),
        "positive_count": result.get("positive_count"),
        "negative_count": result.get("negative_count"),
        "threshold": result.get("threshold"),
        "metrics": result.get("metrics"),
        "confidence_intervals": result.get("confidence_intervals"),
    }


def _profile_projection(profile: Mapping[str, Any] | None) -> dict[str, Any]:
    if profile is None:
        return {"status": "NOT_ADMITTED"}
    return {
        "status": profile.get("status"),
        "profile_id": profile.get("profile_id"),
        "profile_hash": profile.get("profile_hash"),
        "threshold": profile.get("threshold"),
        "runtime_activation_permitted": profile.get("runtime_activation_permitted"),
    }


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
    dataset = _load_dataset(DEFAULT_V2_PATH)
    protected = [
        *(str(case["query"]) for case in dataset["cases"]),
        *(
            str(document["text"])
            for case in dataset["cases"]
            for document in case["documents"]
        ),
        *(str(environ.get(key, "")) for key in PROTECTED_ENV_KEYS if environ.get(key)),
    ]
    if any(len(value) >= 4 and value in serialized for value in protected):
        raise ValueError("S20Q evidence contains protected data")


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
        calibration = _mapping(result.get("calibration"))
        holdout = _mapping(result.get("holdout"))
        return (
            "gb2_s20q_multisignal_live_holdout=pass "
            f"threshold={calibration.get('selected_threshold')} "
            f"holdout={holdout.get('status')} "
            f"samples={calibration.get('sample_count')}/"
            f"{holdout.get('sample_count')}"
        )
    if status == "skipped":
        return "gb2_s20q_multisignal_live_holdout=skipped"
    return (
        "gb2_s20q_multisignal_live_holdout=fail "
        f"error={result.get('failure_code', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20q_multisignal_live_holdout()
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
