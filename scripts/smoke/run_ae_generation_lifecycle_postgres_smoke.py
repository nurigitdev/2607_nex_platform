#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable, Mapping
from urllib.parse import unquote, urlsplit
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
    issue_mock_user_token,
    load_env_file,
    redact_database_url,
)
from run_ae_cx_async_generation_postgres_smoke import (  # noqa: E402
    _test_client_adapter,
    _unexpected_retrieval_client,
    _unexpected_sync_client,
)
from run_cx_async_generation_postgres_smoke import (  # noqa: E402
    DeterministicMockGenerationClient,
    _cleanup_probe_rows,
    _probe_residue,
    _run_worker,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ae_generation_lifecycle_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_GENERATION_LIFECYCLE_POSTGRES_SMOKE"
AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
CX_DATABASE_ENV = "NEX_CX_TEST_DATABASE_URL"
AE_DATABASE = "nex_ae_test"
CX_DATABASE = "nex_cx_test"
AE_ROLE = "nex_ae_user"
CX_ROLE = "nex_cx_user"
PRIVATE_OUTPUT = "Deterministic asynchronous generation response."

SmokeExecutor = Callable[..., dict[str, Any]]


def run_ae_generation_lifecycle_postgres_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    executor: SmokeExecutor | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1050",
            "requirement": "S105",
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
                "slice": "1050",
                "requirement": "S105",
                "actual_postgres": True,
                "provider_mode": "deterministic-mock",
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
            evidence["failure_code"] = "ae_generation_lifecycle_smoke_failed"
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
    request_id = f"s105-{probe}"
    tenant_id = f"tenant-s105-{probe[:12]}"
    owner_id = f"owner-s105-{probe[:12]}"
    other_owner_id = f"other-s105-{probe[:12]}"
    race_id = str(uuid4())
    cancel_id = str(uuid4())
    retry_id = str(uuid4())
    race_message = f"S105 private race question {probe}."
    retry_message = f"S105 private retry question {probe}."
    checks: dict[str, bool] = {}
    row_counts: dict[str, int] = {}
    cleanup_counts: dict[str, int] = {}
    response_statuses: dict[str, int] = {}
    response_error_codes: dict[str, str | None] = {}

    ae_engine = build_engine(ae_database_url)
    ae_factory = build_session_factory(ae_engine)
    ae_prompt_store = SqlAlchemyAePromptRegistryStore(ae_factory)
    ae_chat_store = SqlAlchemyChatInteractionStore(ae_factory)
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

    with tempfile.TemporaryDirectory(prefix="nex-cx-s105-") as temp_dir:
        request_store = FileSystemCxPrivateTextStore(Path(temp_dir) / "requests")
        output_store = FileSystemCxPrivateTextStore(Path(temp_dir) / "outputs")
        generation_repository = SqlAlchemyGenerationRuntimeRepository(
            cx_runtime.api_session_factory,
            source_kind="s105-postgres",
        )
        generation_runtime = GroundedGenerationRuntime(
            admission_repository=SqlAlchemyGenerationAdmissionRepository(
                cx_runtime.api_session_factory
            ),
            execution_repository=generation_repository,
            private_output_store=output_store,
        )
        register_async_generation_operations_routes(
            cx_app,
            job_queue=cx_runtime.job_queue,
            runtime=generation_runtime,
            request_store=request_store,
            read_model=GenerationReadModel(generation_repository, output_store),
            event_emitter=OperationalEventEmitter(
                service_id="nex-cx",
                store=cx_runtime.operational_event_store,
            ),
        )
        leases = SqlAlchemyCxWorkerLeaseStore(cx_runtime.worker_session_factory)
        try:
            with TestClient(cx_app) as cx_client:
                ae_app = build_service_app(SERVICE_SPECS["nex-ae-api"])
                register_chat_routes(
                    ae_app,
                    store=ae_chat_store,
                    cx_client=_unexpected_sync_client(),
                    cx_async_client=_test_client_adapter(cx_client),
                    retrieval_client=_unexpected_retrieval_client(),
                    prompt_store=ae_prompt_store,
                    event_emitter=OperationalEventEmitter(
                        service_id="nex-ae-api",
                        store=SqlAlchemyOperationalEventStore(ae_factory),
                    ),
                )
                with TestClient(ae_app) as ae_client:
                    race_headers = _ae_headers(
                        tenant_id,
                        owner_id,
                        trace_id=trace_id,
                        request_id=f"{request_id}-race",
                    )
                    cancel_headers = _ae_headers(
                        tenant_id,
                        owner_id,
                        trace_id=trace_id,
                        request_id=f"{request_id}-cancel",
                    )
                    retry_headers = _ae_headers(
                        tenant_id,
                        owner_id,
                        trace_id=trace_id,
                        request_id=f"{request_id}-retry",
                    )
                    race_admission = ae_client.post(
                        "/api/v1/chat/interactions",
                        json=_async_payload(race_id, race_message),
                        headers=race_headers,
                    )
                    race_queued = ae_client.get(
                        f"/api/v1/chat/interactions/{race_id}/progress",
                        headers=race_headers,
                    )
                    provider = DeterministicMockGenerationClient()
                    worker_result = _run_worker(
                        cx_runtime.job_queue,
                        leases,
                        generation_runtime,
                        request_store,
                        provider,
                        worker_id=f"s105-worker-{probe}",
                        observed_at=datetime.now(UTC) + timedelta(seconds=5),
                    )
                    race_cancel = ae_client.post(
                        f"/api/v1/chat/interactions/{race_id}/cancel",
                        headers=race_headers,
                    )
                    hidden_progress = ae_client.get(
                        f"/api/v1/chat/interactions/{race_id}/progress",
                        headers=_ae_headers(
                            tenant_id,
                            other_owner_id,
                            trace_id=trace_id,
                            request_id=f"{request_id}-hidden",
                        ),
                    )

                    cancel_admission = ae_client.post(
                        "/api/v1/chat/interactions",
                        json=_async_payload(cancel_id, retry_message),
                        headers=cancel_headers,
                    )
                    cancel_result = ae_client.post(
                        f"/api/v1/chat/interactions/{cancel_id}/cancel",
                        headers=cancel_headers,
                    )
                    recovery = ae_client.get(
                        f"/api/v1/chat/interactions/{cancel_id}/recovery",
                        headers=cancel_headers,
                    )
                    retry_result = ae_client.post(
                        f"/api/v1/chat/interactions/{cancel_id}/retry",
                        json=_async_payload(retry_id, retry_message),
                        headers=retry_headers,
                    )
                    retry_progress = ae_client.get(
                        f"/api/v1/chat/interactions/{retry_id}/progress",
                        headers=retry_headers,
                    )
                    responses = {
                        "race_admission": race_admission,
                        "race_progress": race_queued,
                        "race_cancel": race_cancel,
                        "hidden_progress": hidden_progress,
                        "cancel_admission": cancel_admission,
                        "cancel": cancel_result,
                        "recovery": recovery,
                        "retry": retry_result,
                        "retry_progress": retry_progress,
                    }
                    response_statuses.update(
                        {name: response.status_code for name, response in responses.items()}
                    )
                    response_error_codes.update(
                        {
                            name: (
                                response.json().get("error_code")
                                if isinstance(response.json(), dict)
                                else None
                            )
                            for name, response in responses.items()
                        }
                    )

            with ae_engine.connect() as connection:
                ae_database, ae_role = connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
                row_counts["ae_chat"] = int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM ae_chat_interactions "
                            "WHERE trace_id = :trace_id"
                        ),
                        {"trace_id": trace_id},
                    ).scalar_one()
                )
                row_counts["ae_lifecycle_events"] = int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM service_operational_events "
                            "WHERE trace_id = :trace_id AND "
                            "event_type = 'ae.generation_lifecycle.action_observed'"
                        ),
                        {"trace_id": trace_id},
                    ).scalar_one()
                )
                summaries = connection.execute(
                    text(
                        "SELECT chat_interaction_id, generation_summary "
                        "FROM ae_chat_interactions WHERE trace_id = :trace_id"
                    ),
                    {"trace_id": trace_id},
                ).mappings().all()
            with cx_runtime.api_engine.connect() as connection:
                cx_database, cx_role = connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
                row_counts["cx_jobs"] = int(
                    connection.execute(
                        text("SELECT count(*) FROM service_jobs WHERE trace_id = :trace_id"),
                        {"trace_id": trace_id},
                    ).scalar_one()
                )
                row_counts["cx_executions"] = int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM cx_generation_executions "
                            "WHERE trace_id = :trace_id"
                        ),
                        {"trace_id": trace_id},
                    ).scalar_one()
                )

            ae_restart_engine = build_engine(ae_database_url)
            cx_restart_engine = build_engine(cx_database_url)
            try:
                restarted_store = SqlAlchemyChatInteractionStore(
                    build_session_factory(ae_restart_engine)
                )
                restarted_race = restarted_store.get_for_owner(
                    race_id, tenant_id=tenant_id, owner_user_id=owner_id
                )
                restarted_retry = restarted_store.get_for_owner(
                    retry_id, tenant_id=tenant_id, owner_user_id=owner_id
                )
                retry_job_id = (
                    retry_result.json()
                    .get("generation", {})
                    .get("async_generation", {})
                    .get("job_id")
                )
                restarted_job = SqlAlchemyJobQueue(
                    build_session_factory(cx_restart_engine)
                ).get_job(str(retry_job_id))
            finally:
                ae_restart_engine.dispose()
                cx_restart_engine.dispose()

            persisted_summaries = json.dumps(
                [dict(row) for row in summaries],
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            retry_body = retry_result.json()
            lineage = retry_body.get("generation", {}).get("retry_lineage", {})
            checks.update(
                {
                    "actual_ae_test_database": ae_database == AE_DATABASE,
                    "actual_ae_test_role": ae_role == AE_ROLE,
                    "actual_cx_test_database": cx_database == CX_DATABASE,
                    "actual_cx_test_role": cx_role == CX_ROLE,
                    "race_admitted": race_admission.status_code == 202,
                    "queued_progress_read": race_queued.status_code == 200
                    and race_queued.json().get("cx_job_status") == "QUEUED",
                    "worker_completed": worker_result["succeeded_count"] == 1
                    and provider.call_count == 1,
                    "terminal_state_won_cancel_race": race_cancel.status_code == 200
                    and race_cancel.json().get("status") == "COMPLETED"
                    and race_cancel.json().get("cx_status") == "SUCCEEDED",
                    "owner_isolation_enforced": hidden_progress.status_code == 404,
                    "cancel_admitted": cancel_admission.status_code == 202,
                    "queued_cancel_persisted": cancel_result.status_code == 200
                    and cancel_result.json().get("cx_status") == "CANCELLED",
                    "recovery_retry_eligible": recovery.status_code == 200
                    and recovery.json().get("action") == "RETRY_AS_CHILD"
                    and recovery.json().get("eligible") is True,
                    "retry_child_admitted": retry_result.status_code == 202,
                    "retry_lineage_persisted": lineage.get("parent_interaction_id")
                    == cancel_id
                    and lineage.get("raw_input_included") is False,
                    "retry_progress_read": retry_progress.status_code == 200
                    and retry_progress.json().get("cx_job_status") == "QUEUED",
                    "ae_rows_persisted": row_counts["ae_chat"] == 3,
                    "cx_rows_persisted": row_counts["cx_jobs"] == 3
                    and row_counts["cx_executions"] == 2,
                    "metadata_events_persisted": row_counts[
                        "ae_lifecycle_events"
                    ] >= 4,
                    "private_content_not_persisted": PRIVATE_OUTPUT
                    not in persisted_summaries,
                    "restart_read_succeeded": restarted_race is not None
                    and restarted_race.get("status") == "COMPLETED"
                    and restarted_retry is not None
                    and restarted_job is not None,
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
                cleanup_counts["ae_render_events"] = int(
                    connection.execute(
                        text(
                            "DELETE FROM ae_prompt_render_events "
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
                            "WHERE trace_id = :trace_id"
                        ),
                        {"trace_id": trace_id},
                    ).rowcount
                    or 0
                )
            _cleanup_probe_rows(
                cx_runtime.api_engine,
                trace_id=trace_id,
                request_id=request_id,
            )
            cleanup_counts["cx_remaining"] = _probe_residue(
                cx_runtime.api_engine,
                trace_id=trace_id,
                request_id=request_id,
            )
            with ae_engine.connect() as connection:
                cleanup_counts["ae_remaining"] = sum(
                    int(value)
                    for value in connection.execute(
                        text(
                            "SELECT "
                            "(SELECT count(*) FROM ae_chat_interactions "
                            " WHERE trace_id = :trace_id), "
                            "(SELECT count(*) FROM service_operational_events "
                            " WHERE trace_id = :trace_id OR request_id = :request_id), "
                            "(SELECT count(*) FROM ae_prompt_render_events "
                            " WHERE trace_id = :trace_id OR request_id = :request_id)"
                        ),
                        {"trace_id": trace_id, "request_id": request_id},
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
        "response_statuses": response_statuses,
        "response_error_codes": response_error_codes,
        "probe_id": probe,
    }


def _async_payload(interaction_id: str, message: str) -> dict[str, Any]:
    return {
        "interaction_id": interaction_id,
        "user_message": message,
        "generation": {"execution_strategy": "ASYNCHRONOUS"},
    }


def _ae_headers(
    tenant_id: str,
    owner_id: str,
    *,
    trace_id: str,
    request_id: str,
) -> dict[str, str]:
    token = issue_mock_user_token(tenant_id=tenant_id, user_id=owner_id)
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _target_url_allowed(database_url: str, *, role: str, database: str) -> bool:
    try:
        parsed = urlsplit(database_url)
        return (
            unquote(parsed.username or "") == role
            and unquote(parsed.path.lstrip("/")) == database
        )
    except ValueError:
        return False


def _migration_current(migration: object) -> bool:
    planned = tuple(getattr(migration, "planned", ()))
    applied = tuple(getattr(migration, "applied", ()))
    skipped = tuple(getattr(migration, "skipped", ()))
    return bool(planned) and len(planned) == len(applied) + len(skipped)


def _migration_summary(migration: object) -> dict[str, Any]:
    planned = tuple(getattr(migration, "planned", ()))
    return {
        "planned_count": len(planned),
        "applied_count": len(tuple(getattr(migration, "applied", ()))),
        "skipped_count": len(tuple(getattr(migration, "skipped", ()))),
        "latest_version": planned[-1] if planned else None,
    }


def _redact_detail(detail: str, *, database_urls: tuple[str, ...]) -> str:
    redacted = detail
    for database_url in database_urls:
        redacted = redacted.replace(database_url, redact_database_url(database_url))
        password = urlsplit(database_url).password
        if password:
            redacted = redacted.replace(unquote(password), "***")
    return redacted


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1050",
        "requirement": "S105",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"ae_generation_lifecycle_postgres=skipped reason={SMOKE_ENV}"
    checks = evidence.get("checks") or {}
    cleanup = evidence.get("cleanup_counts") or {}
    identity = evidence.get("database_identity") or {}
    return (
        "ae_generation_lifecycle_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"ae={identity.get('ae', {}).get('database', 'not-run')} "
        f"cx={identity.get('cx', {}).get('database', 'not-run')} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"cleanup={cleanup.get('ae_remaining', 'not-run')}/"
        f"{cleanup.get('cx_remaining', 'not-run')} "
        f"remote_required={evidence.get('remote_provider_required', False)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run protected S105 AE generation lifecycle PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_generation_lifecycle_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
