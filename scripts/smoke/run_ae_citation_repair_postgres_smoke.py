#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable, Mapping
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-cx",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_ae_api.chat import SqlAlchemyChatInteractionStore, register_chat_routes  # noqa: E402
from nex_ae_api.prompt_persistence import SqlAlchemyAePromptRegistryStore  # noqa: E402
from nex_ae_api.prompts import seed_ae_prompt_registry  # noqa: E402
from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.async_generation_operations import (  # noqa: E402
    register_async_generation_operations_routes,
)
from nex_cx.generation_read_model import GenerationReadModel  # noqa: E402
from nex_cx.generation_repository import SqlAlchemyGenerationRuntimeRepository  # noqa: E402
from nex_cx.generation_runtime import (  # noqa: E402
    GroundedGenerationRuntime,
    SqlAlchemyGenerationAdmissionRepository,
)
from nex_cx.private_text_store import FileSystemCxPrivateTextStore  # noqa: E402
from nex_cx.worker_leases import SqlAlchemyCxWorkerLeaseStore  # noqa: E402
from nex_runtime import (  # noqa: E402
    OperationalEventEmitter,
    SERVICE_SPECS,
    SqlAlchemyJobQueue,
    SqlAlchemyOperationalEventStore,
    attach_service_persistence_runtime,
    build_engine,
    build_service_app,
    build_session_factory,
    load_env_file,
    redact_database_url,
)
from run_ae_cx_async_generation_postgres_smoke import (  # noqa: E402
    _ae_headers,
    _migration_current,
    _migration_summary,
    _redact_detail,
    _target_url_allowed,
    _test_client_adapter,
    _unexpected_sync_client,
)
from run_cx_async_generation_postgres_smoke import (  # noqa: E402
    _cleanup_probe_rows,
    _probe_residue,
    _run_worker,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ae_citation_repair_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_CITATION_REPAIR_POSTGRES_SMOKE"
AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
CX_DATABASE_ENV = "NEX_CX_TEST_DATABASE_URL"
AE_DATABASE = "nex_ae_test"
CX_DATABASE = "nex_cx_test"
AE_ROLE = "nex_ae_user"
CX_ROLE = "nex_cx_user"
PRIVATE_INVALID_OUTPUT = "S106 private invalid answer without a citation."
PRIVATE_REPAIRED_OUTPUT = "S106 private repaired grounded answer [1]."

SmokeExecutor = Callable[..., dict[str, Any]]


class StaticRetrievalPackageStore:
    def __init__(self, package: Mapping[str, Any]) -> None:
        self._package = deepcopy(dict(package))

    def get_retrieval_package(
        self, retrieval_package_id: str
    ) -> dict[str, Any] | None:
        if retrieval_package_id != self._package["retrieval_package_id"]:
            return None
        return deepcopy(self._package)


class DeterministicRetrievalClient:
    def __init__(self, package: Mapping[str, Any]) -> None:
        self._package = deepcopy(dict(package))
        self.call_count = 0

    def create_retrieval_context(self, payload, *, request_id, trace_id):
        del payload, request_id, trace_id
        self.call_count += 1
        return deepcopy(self._package)


class CitationRepairMockGenerationClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def create_generation(self, payload, *, request_id, trace_id):
        self.calls.append(deepcopy(dict(payload)))
        output = (
            PRIVATE_INVALID_OUTPUT
            if self.call_count == 1
            else PRIVATE_REPAIRED_OUTPUT
        )
        return {
            "mo_generation_id": f"s106-mock-mo-{self.call_count}",
            "alias": payload["alias"],
            "model_revision": "s106-deterministic-mock-v1",
            "deployment_id": "local-mock",
            "provider_type": "mock-generation",
            "output": {"type": "text", "text": output},
            "finish_reason": "STOP",
            "usage": {
                "input_tokens": 8,
                "output_tokens": 8,
                "total_tokens": 16,
            },
            "runtime_metadata": {
                "request_id": request_id,
                "trace_id": trace_id,
            },
        }


class CountingAsyncClient:
    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.handoff_call_count = 0

    def admit_generation(self, *args, **kwargs):
        return self.delegate.admit_generation(*args, **kwargs)

    def get_handoff(self, *args, **kwargs):
        self.handoff_call_count += 1
        return self.delegate.get_handoff(*args, **kwargs)

    def get_job(self, *args, **kwargs):
        return self.delegate.get_job(*args, **kwargs)

    def cancel_job(self, *args, **kwargs):
        return self.delegate.cancel_job(*args, **kwargs)


def run_ae_citation_repair_postgres_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    executor: SmokeExecutor | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1060",
            "requirement": "S106",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
        }
    ae_url = env.get(AE_DATABASE_ENV, "")
    cx_url = env.get(CX_DATABASE_ENV, "")
    if not ae_url or not cx_url:
        return _failure(
            "database_url_missing",
            f"{AE_DATABASE_ENV} and {CX_DATABASE_ENV} are required.",
        )
    if not _target_url_allowed(ae_url, role=AE_ROLE, database=AE_DATABASE):
        return _failure(
            "ae_target_not_allowed",
            f"AE database target must be {AE_ROLE}@.../{AE_DATABASE}.",
        )
    if not _target_url_allowed(cx_url, role=CX_ROLE, database=CX_DATABASE):
        return _failure(
            "cx_target_not_allowed",
            f"CX database target must be {CX_ROLE}@.../{CX_DATABASE}.",
        )

    try:
        ae_migration = run_service_migrations(
            "nex-ae-api", database_url=ae_url, profile="test"
        )
        cx_migration = run_service_migrations(
            "nex-cx", database_url=cx_url, profile="test"
        )
        evidence = (executor or _execute_postgres_smoke)(
            ae_database_url=ae_url,
            cx_database_url=cx_url,
        )
        evidence["checks"] = {
            "ae_migration_current": _migration_current(ae_migration),
            "cx_migration_current": _migration_current(cx_migration),
            **evidence.get("checks", {}),
        }
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "1060",
                "requirement": "S106",
                "actual_postgres": True,
                "provider_mode": "deterministic-citation-repair-mock",
                "remote_provider_required": False,
                "databases": {
                    "ae": redact_database_url(ae_url),
                    "cx": redact_database_url(cx_url),
                },
                "migrations": {
                    "ae": _migration_summary(ae_migration),
                    "cx": _migration_summary(cx_migration),
                },
            }
        )
        evidence["failed_checks"] = [
            name for name, passed in evidence["checks"].items() if not passed
        ]
        evidence["status"] = "PASS" if not evidence["failed_checks"] else "FAIL"
        if evidence["failed_checks"]:
            evidence["failure_code"] = "ae_citation_repair_smoke_failed"
        return evidence
    except (MigrationError, SQLAlchemyError, OSError, ValueError, RuntimeError) as exc:
        return _failure(
            "execution_failed",
            _redact_detail(str(exc), database_urls=(ae_url, cx_url)),
        )
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__)


def _execute_postgres_smoke(  # pragma: no cover - protected PostgreSQL evidence
    *,
    ae_database_url: str,
    cx_database_url: str,
) -> dict[str, Any]:
    probe = uuid4().hex
    trace_id = uuid4().hex
    request_id = f"s106-{probe}"
    interaction_id = str(uuid4())
    tenant_id = f"tenant-s106-{probe[:12]}"
    owner_id = f"owner-s106-{probe[:12]}"
    other_owner_id = f"other-s106-{probe[:12]}"
    private_message = f"S106 private grounded question {probe}."
    private_evidence = f"S106 private evidence {probe}."
    retrieval_package = _retrieval_package(
        probe=probe,
        tenant_id=tenant_id,
        owner_id=owner_id,
        private_evidence=private_evidence,
    )
    checks: dict[str, bool] = {}
    row_counts: dict[str, int] = {}
    cleanup_counts: dict[str, int] = {}
    render_event_id: str | None = None
    job_id: str | None = None
    cx_generation_id: str | None = None

    ae_engine = build_engine(ae_database_url)
    ae_factory = build_session_factory(ae_engine)
    ae_prompt_store = SqlAlchemyAePromptRegistryStore(ae_factory)
    ae_chat_store = SqlAlchemyChatInteractionStore(ae_factory)
    ae_event_store = SqlAlchemyOperationalEventStore(ae_factory)
    seed_ae_prompt_registry(ae_prompt_store)

    cx_app = build_service_app(SERVICE_SPECS["nex-cx"])
    cx_runtime = attach_service_persistence_runtime(
        cx_app,
        SERVICE_SPECS["nex-cx"],
        environ={
            SERVICE_SPECS["nex-cx"].database_env: cx_database_url,
            "NEX_CX_PERSISTENCE_MODE": "postgres",
        },
    )
    if (
        cx_runtime.api_engine is None
        or cx_runtime.worker_engine is None
        or cx_runtime.api_session_factory is None
        or cx_runtime.worker_session_factory is None
    ):
        raise RuntimeError("CX PostgreSQL persistence runtime is unavailable")

    with tempfile.TemporaryDirectory(prefix="nex-cx-s106-") as temp_dir:
        request_store = FileSystemCxPrivateTextStore(Path(temp_dir) / "requests")
        output_store = FileSystemCxPrivateTextStore(Path(temp_dir) / "outputs")
        generation_repository = SqlAlchemyGenerationRuntimeRepository(
            cx_runtime.api_session_factory,
            source_kind="s106-postgres",
        )
        generation_runtime = GroundedGenerationRuntime(
            admission_repository=SqlAlchemyGenerationAdmissionRepository(
                cx_runtime.api_session_factory
            ),
            execution_repository=generation_repository,
            private_output_store=output_store,
        )
        package_store = StaticRetrievalPackageStore(retrieval_package)
        register_async_generation_operations_routes(
            cx_app,
            job_queue=cx_runtime.job_queue,
            runtime=generation_runtime,
            request_store=request_store,
            retrieval_store=package_store,
            read_model=GenerationReadModel(generation_repository, output_store),
            event_emitter=OperationalEventEmitter(
                service_id="nex-cx",
                store=cx_runtime.operational_event_store,
            ),
        )
        leases = SqlAlchemyCxWorkerLeaseStore(cx_runtime.worker_session_factory)
        retrieval_client = DeterministicRetrievalClient(retrieval_package)
        provider = CitationRepairMockGenerationClient()

        try:
            _seed_retrieval_package(
                cx_runtime.api_engine,
                retrieval_package=retrieval_package,
                trace_id=trace_id,
                request_id=request_id,
            )
            with TestClient(cx_app) as cx_client:
                async_client = CountingAsyncClient(_test_client_adapter(cx_client))
                ae_app = build_service_app(SERVICE_SPECS["nex-ae-api"])
                register_chat_routes(
                    ae_app,
                    store=ae_chat_store,
                    cx_client=_unexpected_sync_client(),
                    cx_async_client=async_client,
                    retrieval_client=retrieval_client,
                    prompt_store=ae_prompt_store,
                    event_emitter=OperationalEventEmitter(
                        service_id="nex-ae-api",
                        store=ae_event_store,
                    ),
                )
                with TestClient(ae_app) as ae_client:
                    owner_headers = _ae_headers(
                        tenant_id,
                        owner_id,
                        trace_id=trace_id,
                        request_id=request_id,
                    )
                    admission = ae_client.post(
                        "/api/v1/chat/interactions",
                        json={
                            "interaction_id": interaction_id,
                            "user_message": private_message,
                            "retrieval": {
                                "purpose": "grounded_answer",
                                "top_k": 1,
                            },
                            "generation": {
                                "execution_strategy": "ASYNCHRONOUS"
                            },
                        },
                        headers=owner_headers,
                    )
                    admission_body = admission.json()
                    projection = admission_body.get("generation", {}).get(
                        "async_generation", {}
                    )
                    job_id = projection.get("job_id")
                    cx_generation_id = projection.get("cx_generation_id")
                    worker_result = _run_worker(
                        cx_runtime.job_queue,
                        leases,
                        generation_runtime,
                        request_store,
                        provider,
                        worker_id=f"s106-worker-{probe}",
                        observed_at=datetime.now(UTC) + timedelta(seconds=5),
                    )
                    refresh = ae_client.post(
                        f"/api/v1/chat/interactions/{interaction_id}/refresh",
                        headers=owner_headers,
                    )
                    refresh_body = refresh.json()
                    owner_quality = ae_client.get(
                        f"/api/v1/chat/interactions/{interaction_id}/citation-quality",
                        headers=owner_headers,
                    )
                    other_quality = ae_client.get(
                        f"/api/v1/chat/interactions/{interaction_id}/citation-quality",
                        headers=_ae_headers(
                            tenant_id,
                            other_owner_id,
                            trace_id=trace_id,
                            request_id=request_id,
                        ),
                    )

            flow_state = {
                "admission_status": admission.status_code,
                "admission_error_code": admission_body.get("error_code"),
                "worker_succeeded_count": worker_result.get("succeeded_count"),
                "worker_retry_scheduled_count": worker_result.get(
                    "retry_scheduled_count"
                ),
                "worker_dead_lettered_count": worker_result.get(
                    "dead_lettered_count"
                ),
                "provider_call_count": provider.call_count,
                "refresh_status": refresh.status_code,
                "refresh_error_code": refresh_body.get("error_code"),
            }
            current_job = (
                cx_runtime.job_queue.get_job(str(job_id)) if job_id else None
            )
            if isinstance(current_job, Mapping):
                current_error = current_job.get("error")
                if isinstance(current_error, Mapping):
                    flow_state["job_error_code"] = current_error.get("error_code")
            if not (
                admission.status_code == 202
                and worker_result.get("succeeded_count") == 1
                and refresh.status_code == 200
            ):
                raise RuntimeError(
                    "Citation repair smoke flow did not complete: "
                    f"{json.dumps(flow_state, sort_keys=True)}"
                )

            completed = refresh_body.get("interaction", {})
            result = refresh_body.get("result", {})
            workflow = completed.get("generation", {}).get("citation_workflow", {})
            owner_workflow = owner_quality.json()
            render_event_id = (
                completed.get("generation", {})
                .get("policy", {})
                .get("prompt_render_event_ref", {})
                .get("prompt_render_event_id")
            )

            with ae_engine.connect() as connection:
                ae_database, ae_role = connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
                generation_summary = connection.execute(
                    text(
                        "SELECT generation_summary FROM ae_chat_interactions "
                        "WHERE chat_interaction_id = :interaction_id"
                    ),
                    {"interaction_id": interaction_id},
                ).scalar_one()
                event_rows = connection.execute(
                    text(
                        "SELECT details FROM service_operational_events "
                        "WHERE trace_id = :trace_id AND "
                        "event_type = 'ae.citation_quality.workflow_observed'"
                    ),
                    {"trace_id": trace_id},
                ).scalars().all()
                row_counts["ae_chat"] = 1
                row_counts["ae_citation_events"] = len(event_rows)

            with cx_runtime.api_engine.connect() as connection:
                cx_database, cx_role = connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
                request_metadata = connection.execute(
                    text(
                        "SELECT request_metadata FROM cx_generation_executions "
                        "WHERE trace_id = :trace_id"
                    ),
                    {"trace_id": trace_id},
                ).scalar_one()
                row_counts["cx_job"] = int(
                    connection.execute(
                        text("SELECT count(*) FROM service_jobs WHERE job_id = :job_id"),
                        {"job_id": job_id},
                    ).scalar_one()
                )
                row_counts["cx_execution"] = 1

            ae_restart_engine = build_engine(ae_database_url)
            cx_restart_engine = build_engine(cx_database_url)
            try:
                restarted_chat = SqlAlchemyChatInteractionStore(
                    build_session_factory(ae_restart_engine)
                ).get_for_owner(
                    interaction_id,
                    tenant_id=tenant_id,
                    owner_user_id=owner_id,
                )
                restarted_job = SqlAlchemyJobQueue(
                    build_session_factory(cx_restart_engine)
                ).get_job(str(job_id))
                restarted_generation = SqlAlchemyGenerationRuntimeRepository(
                    build_session_factory(cx_restart_engine),
                    source_kind="s106-postgres-restart",
                ).get(
                    str(cx_generation_id),
                    access_context=CxAccessContext(
                        caller_service_id="nex-ae-api",
                        tenant_id=tenant_id,
                        subject_id=owner_id,
                        request_id=request_id,
                        trace_id=trace_id,
                        scopes=("service:call",),
                    ),
                )
            finally:
                ae_restart_engine.dispose()
                cx_restart_engine.dispose()

            persisted_summary = _json_mapping(generation_summary)
            persisted_metadata = _json_mapping(request_metadata)
            event_details = [_json_mapping(item) for item in event_rows]
            persisted_workflow = persisted_summary.get("citation_workflow", {})
            repair = persisted_metadata.get("citation_repair", {})
            serialized_safe_metadata = json.dumps(
                {
                    "ae_generation_summary": persisted_summary,
                    "ae_event_details": event_details,
                    "cx_request_metadata": persisted_metadata,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            private_values = (
                private_message,
                private_evidence,
                PRIVATE_INVALID_OUTPUT,
                PRIVATE_REPAIRED_OUTPUT,
            )
            first_call, second_call = provider.calls
            checks.update(
                {
                    "actual_ae_test_database": ae_database == AE_DATABASE,
                    "actual_ae_test_role": ae_role == AE_ROLE,
                    "actual_cx_test_database": cx_database == CX_DATABASE,
                    "actual_cx_test_role": cx_role == CX_ROLE,
                    "grounded_async_admitted": admission.status_code == 202
                    and admission_body.get("status") == "PENDING"
                    and retrieval_client.call_count == 1
                    and row_counts["ae_chat"] == 1,
                    "bounded_repair_executed": worker_result["succeeded_count"] == 1
                    and provider.call_count == 2
                    and row_counts["cx_job"] == 1
                    and row_counts["cx_execution"] == 1,
                    "same_retrieval_package_reused": (
                        first_call.get("metadata", {}).get("retrieval_package_id")
                        == retrieval_package["retrieval_package_id"]
                        == second_call.get("metadata", {}).get("retrieval_package_id")
                        and first_call.get("metadata", {}).get("retrieval_package_hash")
                        == retrieval_package["package_hash"]
                        == second_call.get("metadata", {}).get("retrieval_package_hash")
                    ),
                    "cx_repair_metadata_persisted": repair.get("attempted") is True
                    and repair.get("attempt_count") == 1
                    and repair.get("max_attempts") == 1
                    and repair.get("same_retrieval_package") is True
                    and repair.get("invalid_output_included") is False,
                    "ae_refresh_persisted_repaired_workflow": (
                        refresh.status_code == 200
                        and completed.get("status") == "COMPLETED"
                        and result.get("handoff_status") == "READY"
                        and workflow.get("workflow_status") == "REPAIRED"
                        and persisted_workflow == workflow
                    ),
                    "owner_quality_reads_durable_projection": (
                        owner_quality.status_code == 200
                        and owner_workflow == workflow
                        and async_client.handoff_call_count == 1
                    ),
                    "owner_isolation_enforced_before_handoff": (
                        other_quality.status_code == 404
                        and async_client.handoff_call_count == 1
                    ),
                    "metadata_only_observability_persisted": (
                        row_counts["ae_citation_events"] == 1
                        and event_details[0].get("outcome")
                        == "BOUNDED_REPAIR_SUCCEEDED"
                        and event_details[0].get("repair_attempt_count") == 1
                        and event_details[0].get("raw_invalid_output_included")
                        is False
                    ),
                    "private_content_excluded_from_metadata": not any(
                        value in serialized_safe_metadata for value in private_values
                    ),
                    "repaired_content_transient": (
                        result.get("content") == PRIVATE_REPAIRED_OUTPUT
                        and refresh_body.get("content_persisted_by_ae") is False
                    ),
                    "restart_reads_preserve_workflow": (
                        restarted_chat is not None
                        and restarted_chat.get("generation", {}).get(
                            "citation_workflow"
                        )
                        == workflow
                        and restarted_job is not None
                        and restarted_job.get("status") == "SUCCEEDED"
                        and restarted_generation is not None
                        and restarted_generation.get("request_metadata", {}).get(
                            "citation_repair"
                        )
                        == repair
                    ),
                }
            )
        finally:
            with ae_engine.begin() as connection:
                cleanup_counts["ae_events"] = int(
                    connection.execute(
                        text(
                            "DELETE FROM service_operational_events "
                            "WHERE trace_id = :trace_id OR request_id = :request_id"
                        ),
                        {"trace_id": trace_id, "request_id": request_id},
                    ).rowcount
                    or 0
                )
                cleanup_counts["ae_chat"] = int(
                    connection.execute(
                        text(
                            "DELETE FROM ae_chat_interactions "
                            "WHERE chat_interaction_id = :interaction_id"
                        ),
                        {"interaction_id": interaction_id},
                    ).rowcount
                    or 0
                )
                if render_event_id:
                    cleanup_counts["ae_render_event"] = int(
                        connection.execute(
                            text(
                                "DELETE FROM ae_prompt_render_events "
                                "WHERE prompt_render_event_id = :event_id"
                            ),
                            {"event_id": render_event_id},
                        ).rowcount
                        or 0
                    )
            _cleanup_probe_rows(
                cx_runtime.api_engine,
                trace_id=trace_id,
                request_id=request_id,
            )
            with cx_runtime.api_engine.begin() as connection:
                cleanup_counts["cx_retrieval_package"] = int(
                    connection.execute(
                        text(
                            "DELETE FROM cx_retrieval_packages "
                            "WHERE retrieval_package_id = :retrieval_package_id"
                        ),
                        {
                            "retrieval_package_id": retrieval_package[
                                "retrieval_package_id"
                            ]
                        },
                    ).rowcount
                    or 0
                )
            cleanup_counts["cx_remaining"] = _probe_residue(
                cx_runtime.api_engine,
                trace_id=trace_id,
                request_id=request_id,
            )
            with cx_runtime.api_engine.connect() as connection:
                cleanup_counts["cx_remaining"] += int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM cx_retrieval_packages "
                            "WHERE retrieval_package_id = :retrieval_package_id"
                        ),
                        {
                            "retrieval_package_id": retrieval_package[
                                "retrieval_package_id"
                            ]
                        },
                    ).scalar_one()
                )
            with ae_engine.connect() as connection:
                cleanup_counts["ae_remaining"] = sum(
                    int(value)
                    for value in connection.execute(
                        text(
                            "SELECT "
                            "(SELECT count(*) FROM ae_chat_interactions "
                            " WHERE chat_interaction_id = :interaction_id), "
                            "(SELECT count(*) FROM service_operational_events "
                            " WHERE trace_id = :trace_id OR request_id = :request_id), "
                            "(SELECT count(*) FROM ae_prompt_render_events "
                            " WHERE prompt_render_event_id = :event_id)"
                        ),
                        {
                            "interaction_id": interaction_id,
                            "trace_id": trace_id,
                            "request_id": request_id,
                            "event_id": render_event_id
                            or "00000000-0000-0000-0000-000000000000",
                        },
                    ).one()
                )
            checks["cleanup_complete"] = (
                cleanup_counts["ae_remaining"] == 0
                and cleanup_counts["cx_remaining"] == 0
            )
            ae_engine.dispose()
            cx_runtime.api_engine.dispose()
            cx_runtime.worker_engine.dispose()

    return {
        "execution_state": "EXECUTED",
        "database_identity": {
            "ae": {"database": ae_database, "role": ae_role},
            "cx": {"database": cx_database, "role": cx_role},
        },
        "checks": checks,
        "row_counts": row_counts,
        "cleanup_counts": cleanup_counts,
        "provider_call_count": provider.call_count,
        "probe_id": probe,
    }


def _retrieval_package(
    *,
    probe: str,
    tenant_id: str,
    owner_id: str,
    private_evidence: str,
) -> dict[str, Any]:
    return {
        "retrieval_package_id": str(uuid4()),
        "tenant_ref_type": "oa.tenant",
        "tenant_ref_id": tenant_id,
        "owner_subject_ref_type": "oa.user",
        "owner_subject_ref_id": owner_id,
        "package_hash": hashlib.sha256(
            f"s106-package:{probe}".encode("utf-8")
        ).hexdigest(),
        "status": "READY",
        "purpose": "grounded_answer",
        "query_text": f"S106 private retrieval query {probe}.",
        "evidence_items": [
            {
                "evidence_id": f"s106-evidence-{probe}",
                "citation_label": "[1]",
                "text": private_evidence,
                "scores": {"final_score": 0.97},
                "quality_flags": [],
            }
        ],
        "score_summary": {
            "best_score": 0.97,
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
        "no_answer_reason": None,
        "warnings": [],
    }


def _seed_retrieval_package(
    engine,
    *,
    retrieval_package: Mapping[str, Any],
    trace_id: str,
    request_id: str,
) -> None:  # pragma: no cover - protected PostgreSQL evidence
    query_hash = hashlib.sha256(
        str(retrieval_package["query_text"]).encode("utf-8")
    ).hexdigest()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO cx_retrieval_packages (
                    retrieval_package_id, package_hash, status, trace_id,
                    request_id, query_text_sha256, query_embedding_provided,
                    query_embedding_dimension, purpose, retrieval_policy_id,
                    retrieval_policy_version, retrieval_policy_hash,
                    retrieval_policy_source, ranker_mix, rerank_state,
                    permission_snapshot_hash, source_summary, score_summary,
                    warning_count, evidence_count, no_answer_reason,
                    tenant_ref_type, tenant_ref_id,
                    owner_subject_ref_type, owner_subject_ref_id
                ) VALUES (
                    :retrieval_package_id, :package_hash, 'READY', :trace_id,
                    :request_id, :query_text_sha256, false, 0,
                    'grounded_answer', 's106-smoke-policy', '1',
                    :retrieval_policy_hash, 'protected-smoke', :ranker_mix,
                    'APPLIED', :permission_snapshot_hash,
                    CAST(:source_summary AS JSONB), CAST(:score_summary AS JSONB),
                    0, 1, NULL, 'oa.tenant', :tenant_ref_id,
                    'oa.user', :owner_subject_ref_id
                )
                """
            ),
            {
                "retrieval_package_id": retrieval_package["retrieval_package_id"],
                "package_hash": retrieval_package["package_hash"],
                "trace_id": trace_id,
                "request_id": request_id,
                "query_text_sha256": query_hash,
                "retrieval_policy_hash": "c" * 64,
                "ranker_mix": retrieval_package["score_summary"]["ranker_mix"],
                "permission_snapshot_hash": "d" * 64,
                "source_summary": json.dumps(retrieval_package["source_summary"]),
                "score_summary": json.dumps(retrieval_package["score_summary"]),
                "tenant_ref_id": retrieval_package["tenant_ref_id"],
                "owner_subject_ref_id": retrieval_package[
                    "owner_subject_ref_id"
                ],
            },
        )


def _json_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, Mapping):
            return dict(decoded)
    raise ValueError("Expected a persisted JSON object.")


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1060",
        "requirement": "S106",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"ae_citation_repair_postgres=skipped reason={SMOKE_ENV}"
    checks = evidence.get("checks") or {}
    cleanup = evidence.get("cleanup_counts") or {}
    identity = evidence.get("database_identity") or {}
    return (
        "ae_citation_repair_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"ae={identity.get('ae', {}).get('database', 'not-run')} "
        f"cx={identity.get('cx', {}).get('database', 'not-run')} "
        f"provider_calls={evidence.get('provider_call_count', 'not-run')} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"cleanup={cleanup.get('ae_remaining', 'not-run')}/"
        f"{cleanup.get('cx_remaining', 'not-run')} "
        f"remote_required={evidence.get('remote_provider_required', False)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run protected AE/CX citation-repair PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_citation_repair_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
