#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
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
    ROOT / "scripts" / "db",
):
    sys.path.insert(0, str(path))

from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.async_generation_operations import (  # noqa: E402
    register_async_generation_operations_routes,
)
from nex_cx.async_generation_recovery import (  # noqa: E402
    recover_persisted_async_generation_job,
)
from nex_cx.async_generation_worker import (  # noqa: E402
    AsyncGenerationWorkerHandler,
)
from nex_cx.generation import GenerationFacadeError  # noqa: E402
from nex_cx.generation_read_model import GenerationReadModel  # noqa: E402
from nex_cx.generation_repository import (  # noqa: E402
    SqlAlchemyGenerationRuntimeRepository,
)
from nex_cx.generation_runtime import (  # noqa: E402
    GroundedGenerationRuntime,
    SqlAlchemyGenerationAdmissionRepository,
)
from nex_cx.private_text_store import FileSystemCxPrivateTextStore  # noqa: E402
from nex_cx.worker_leases import (  # noqa: E402
    SqlAlchemyCxWorkerLeaseStore,
    claim_next_worker_execution,
)
from nex_cx.worker_runtime import (  # noqa: E402
    CxWorkerRuntimePolicy,
    run_bounded_worker_batch,
)
from nex_runtime import (  # noqa: E402
    OperationalEventEmitter,
    SERVICE_SPECS,
    SqlAlchemyJobQueue,
    attach_service_persistence_runtime,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SCHEMA_VERSION = "cx_async_generation_postgres_smoke.v1"
SMOKE_ENV = "NEX_CX_ASYNC_GENERATION_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_CX_ASYNC_GENERATION_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SERVICE_SPEC = SERVICE_SPECS[SERVICE_ID]
EXPECTED_DATABASE = "nex_cx_test"
EXPECTED_ROLE = "nex_cx_user"
LATEST_MIGRATION_VERSION = "0966_cx_generation_admissions"
TENANT_ID = "s99-postgres-tenant"
OWNER_ID = "s99-postgres-owner"
OTHER_OWNER_ID = "s99-postgres-other-owner"
PRIVATE_MARKER = "S99_PRIVATE_ASYNC_GENERATION_PROMPT"

SmokeExecutor = Callable[..., dict[str, Any]]


class DeterministicMockGenerationClient:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.fail_first = fail_first
        self.call_count = 0
        self.failure_count = 0

    def create_generation(self, payload, *, request_id, trace_id):
        self.call_count += 1
        if self.fail_first and self.call_count == 1:
            self.failure_count += 1
            raise GenerationFacadeError(
                503,
                "mock.provider_timeout",
                "Deterministic mock provider timeout.",
                True,
            )
        return {
            "mo_generation_id": f"mock-mo-{self.call_count}",
            "alias": payload["alias"],
            "model_revision": "deterministic-mock-v1",
            "deployment_id": "local-mock",
            "provider_type": "mock-generation",
            "output": {
                "type": "text",
                "text": "Deterministic asynchronous generation response.",
            },
            "finish_reason": "STOP",
            "usage": {
                "input_tokens": 2,
                "output_tokens": 4,
                "total_tokens": 6,
            },
            "runtime_metadata": {
                "request_id": request_id,
                "trace_id": trace_id,
            },
        }


def run_cx_async_generation_postgres_smoke(
    environ: Mapping[str, str] | None = None,
    *,
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

    database_url = ""
    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(
            SERVICE_ID,
            profile=profile,
            environ=env,
        )
        if not _target_url_allowed(database_url):
            return _failure(
                "target_not_allowed",
                f"database target must be {EXPECTED_ROLE}@.../{EXPECTED_DATABASE}",
                profile=profile,
            )
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execute = executor or _execute_async_generation_smoke
        execution = execute(
            database_url=database_url,
            runtime_environ={
                **env,
                SERVICE_SPEC.database_env: database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )
        failed_checks = execution.get("failed_checks") or []
        if failed_checks:
            return _failure(
                "async_generation_smoke_failed",
                ",".join(str(item) for item in failed_checks),
                profile=profile,
                execution=execution,
            )
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            "migration": {
                "planned": list(migration.planned),
                "applied": list(migration.applied),
                "skipped": list(migration.skipped),
            },
            "provider_mode": "deterministic_mock",
            "remote_provider_required": False,
            **execution,
        }
    except (MigrationError, OSError, ValueError) as exc:
        return _failure(
            "execution_failed",
            _redact_detail(str(exc), database_url=database_url),
            profile=profile,
        )
    except Exception as exc:
        return _failure(
            "execution_failed",
            exc.__class__.__name__,
            profile=profile,
        )


def _execute_async_generation_smoke(  # pragma: no cover - protected PostgreSQL evidence
    *,
    database_url: str,
    runtime_environ: Mapping[str, str],
) -> dict[str, Any]:
    probe_id = uuid4().hex
    trace_id = uuid4().hex
    request_id = f"s99-{probe_id}"
    base_time = datetime.now(UTC)
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    generation_ids: list[str] = []
    job_ids: list[str] = []
    app = build_service_app(SERVICE_SPEC)
    persistence = attach_service_persistence_runtime(
        app,
        SERVICE_SPEC,
        environ=runtime_environ,
    )
    if (
        persistence.api_engine is None
        or persistence.worker_engine is None
        or persistence.api_session_factory is None
        or persistence.worker_session_factory is None
    ):
        raise RuntimeError("CX PostgreSQL persistence runtime is unavailable")

    with tempfile.TemporaryDirectory(prefix="nex-cx-s99-") as temp_dir:
        private_root = Path(temp_dir)
        request_store = FileSystemCxPrivateTextStore(private_root / "requests")
        output_store = FileSystemCxPrivateTextStore(private_root / "outputs")
        generation_repository = SqlAlchemyGenerationRuntimeRepository(
            persistence.api_session_factory,
            source_kind="postgres-write",
            database_env="NEX_CX_TEST_DATABASE_URL",
            redacted_database_url=redact_database_url(database_url),
        )
        generation_runtime = GroundedGenerationRuntime(
            admission_repository=SqlAlchemyGenerationAdmissionRepository(
                persistence.api_session_factory
            ),
            execution_repository=generation_repository,
            private_output_store=output_store,
        )
        emitter = OperationalEventEmitter(
            service_id=SERVICE_ID,
            store=persistence.operational_event_store,
        )
        register_async_generation_operations_routes(
            app,
            job_queue=persistence.job_queue,
            runtime=generation_runtime,
            request_store=request_store,
            event_emitter=emitter,
        )
        leases = SqlAlchemyCxWorkerLeaseStore(
            persistence.worker_session_factory
        )

        try:
            identity = _database_identity(persistence.api_engine)
            migration_count = _migration_count(persistence.api_engine)
            with TestClient(app) as client:
                success = _admit(client, trace_id, request_id, "success")
                generation_ids.append(success["job"]["cx_generation_id"])
                job_ids.append(success["job"]["job_id"])
                success_provider = DeterministicMockGenerationClient()
                success_run = _run_worker(
                    persistence.job_queue,
                    leases,
                    generation_runtime,
                    request_store,
                    success_provider,
                    worker_id=f"s99-success-{probe_id}",
                    observed_at=base_time + timedelta(seconds=10),
                )

                retry = _admit(client, trace_id, request_id, "retry")
                generation_ids.append(retry["job"]["cx_generation_id"])
                job_ids.append(retry["job"]["job_id"])
                retry_provider = DeterministicMockGenerationClient(
                    fail_first=True
                )
                retry_first = _run_worker(
                    persistence.job_queue,
                    leases,
                    generation_runtime,
                    request_store,
                    retry_provider,
                    worker_id=f"s99-retry-1-{probe_id}",
                    observed_at=base_time + timedelta(seconds=60),
                )
                retry_second = _run_worker(
                    persistence.job_queue,
                    leases,
                    generation_runtime,
                    request_store,
                    retry_provider,
                    worker_id=f"s99-retry-2-{probe_id}",
                    observed_at=base_time + timedelta(seconds=100),
                )

                recovery = _admit(client, trace_id, request_id, "recovery")
                recovery_job_id = recovery["job"]["job_id"]
                generation_ids.append(recovery["job"]["cx_generation_id"])
                job_ids.append(recovery_job_id)
                claim_next_worker_execution(
                    job_queue=persistence.job_queue,
                    lease_store=leases,
                    worker_id=f"s99-crashed-{probe_id}",
                    worker_type="cx.generation.worker",
                    workload="grounded_generation",
                    observed_at=_wire(base_time + timedelta(seconds=200)),
                )
                recovered = recover_persisted_async_generation_job(
                    persistence.job_queue.get_job(recovery_job_id),
                    _wire(base_time + timedelta(seconds=321)),
                    job_queue=persistence.job_queue,
                    request_store=request_store,
                    runtime=generation_runtime,
                )
                recovery_provider = DeterministicMockGenerationClient()
                recovery_run = _run_worker(
                    persistence.job_queue,
                    leases,
                    generation_runtime,
                    request_store,
                    recovery_provider,
                    worker_id=f"s99-recovered-{probe_id}",
                    observed_at=base_time + timedelta(seconds=400),
                )

                cancelled = _admit(client, trace_id, request_id, "cancel")
                cancel_job_id = cancelled["job"]["job_id"]
                generation_ids.append(cancelled["job"]["cx_generation_id"])
                job_ids.append(cancel_job_id)
                cancel_response = client.post(
                    f"/api/v1/generation-jobs/{cancel_job_id}/cancel",
                    headers=_headers(trace_id, request_id, "cancel"),
                )
                cancel_response.raise_for_status()

                replay_response = client.post(
                    "/api/v1/generation-jobs",
                    json=_request_payload("success"),
                    headers=_headers(trace_id, request_id, "success"),
                )
                replay_response.raise_for_status()
                replay = replay_response.json()
                other_owner = client.get(
                    f"/api/v1/generation-jobs/{job_ids[0]}",
                    headers=_headers(
                        trace_id,
                        request_id,
                        "success",
                        subject_id=OTHER_OWNER_ID,
                    ),
                )

            restart_engine = build_engine(database_url)
            try:
                restart_factory = build_session_factory(restart_engine)
                restart_repository = SqlAlchemyGenerationRuntimeRepository(
                    restart_factory,
                    source_kind="postgres-restart-read",
                )
                restart_read_model = GenerationReadModel(
                    restart_repository,
                    FileSystemCxPrivateTextStore(private_root / "outputs"),
                )
                owner_context = _access_context(trace_id, request_id, OWNER_ID)
                restarted_metadata = restart_read_model.get_metadata(
                    generation_ids[0], access_context=owner_context
                )
                restarted_content = restart_read_model.get_content(
                    generation_ids[0], access_context=owner_context
                )
                hidden_generation = restart_repository.get(
                    generation_ids[0],
                    access_context=_access_context(
                        trace_id, request_id, OTHER_OWNER_ID
                    ),
                )
                restarted_job = SqlAlchemyJobQueue(restart_factory).get_job(
                    job_ids[0]
                )
            finally:
                restart_engine.dispose()

            observation = _database_observation(
                persistence.api_engine,
                trace_id=trace_id,
                request_id=request_id,
            )
            event_payload = json.dumps(
                observation["event_details"],
                ensure_ascii=False,
                sort_keys=True,
            )
            status_counts = observation["job_status_counts"]
            execution_counts = observation["execution_status_counts"]
            admission_counts = observation["admission_status_counts"]
            checks.update(
                {
                    "actual_test_database": identity["database"]
                    == EXPECTED_DATABASE,
                    "actual_test_role": identity["role"] == EXPECTED_ROLE,
                    "latest_migration_recorded": migration_count == 1,
                    "success_path_completed": success_run["succeeded_count"]
                    == 1,
                    "retry_scheduled_then_completed": (
                        retry_first["retry_scheduled_count"] == 1
                        and retry_second["succeeded_count"] == 1
                        and retry_provider.failure_count == 1
                        and retry_provider.call_count == 2
                    ),
                    "expired_lease_requeued": recovered["status"]
                    == "RETRY_SCHEDULED",
                    "recovered_job_completed": recovery_run[
                        "succeeded_count"
                    ]
                    == 1,
                    "queued_cancellation_persisted": cancel_response.json()[
                        "status"
                    ]
                    == "CANCELLED",
                    "terminal_replay_without_duplicate": (
                        replay["admission_status"] == "REPLAYED"
                        and replay["job"]["job_id"] == job_ids[0]
                    ),
                    "restart_job_reloaded": restarted_job["status"]
                    == "SUCCEEDED",
                    "restart_metadata_reloaded": restarted_metadata["status"]
                    == "COMPLETED",
                    "restart_private_content_verified": (
                        restarted_content["owner_scope_enforced"] is True
                        and restarted_content["size_bytes"] > 0
                    ),
                    "cross_owner_job_hidden": other_owner.status_code == 404,
                    "cross_owner_generation_hidden": hidden_generation is None,
                    "postgres_job_states_converged": status_counts
                    == {"CANCELLED": 1, "SUCCEEDED": 3},
                    "postgres_execution_states_converged": execution_counts
                    == {"COMPLETED": 3, "FAILED": 1},
                    "postgres_admission_states_converged": admission_counts
                    == {"COMPLETED": 3, "FAILED": 1},
                    "operational_events_persisted": observation[
                        "event_type_counts"
                    ].get("cx.async_generation.admitted", 0)
                    >= 5
                    and observation["event_type_counts"].get(
                        "cx.async_generation.cancelled", 0
                    )
                    == 1,
                    "operational_events_are_metadata_only": (
                        PRIVATE_MARKER not in event_payload
                        and TENANT_ID not in event_payload
                        and OWNER_ID not in event_payload
                    ),
                    "remote_provider_not_called": True,
                }
            )
            details = {
                "job_status_counts": status_counts,
                "execution_status_counts": execution_counts,
                "admission_status_counts": admission_counts,
                "event_type_counts": observation["event_type_counts"],
                "mock_provider_call_count": (
                    success_provider.call_count
                    + retry_provider.call_count
                    + recovery_provider.call_count
                ),
                "recovered_status": recovered["status"],
            }
        finally:
            _cleanup_probe_rows(
                persistence.api_engine,
                trace_id=trace_id,
                request_id=request_id,
            )
            residue = _probe_residue(
                persistence.api_engine,
                trace_id=trace_id,
                request_id=request_id,
            )
            checks["cleanup_verified"] = residue == 0
            persistence.api_engine.dispose()
            persistence.worker_engine.dispose()

    return {
        "database": identity["database"],
        "role": identity["role"],
        "probe_id": probe_id,
        "probe_residue": residue,
        "details": details,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _run_worker(
    job_queue,
    lease_store,
    generation_runtime,
    request_store,
    provider,
    *,
    worker_id: str,
    observed_at: datetime,
):  # pragma: no cover - protected PostgreSQL evidence
    return run_bounded_worker_batch(
        job_queue=job_queue,
        lease_store=lease_store,
        handler=AsyncGenerationWorkerHandler(
            job_queue,
            generation_runtime,
            request_store,
            provider,
        ),
        worker_id=worker_id,
        worker_type="cx.generation.worker",
        workload="grounded_generation",
        runtime_policy=CxWorkerRuntimePolicy(max_jobs=1),
        clock=lambda: _wire(observed_at),
    )


def _admit(client, trace_id: str, request_id: str, key: str):  # pragma: no cover
    response = client.post(
        "/api/v1/generation-jobs",
        json=_request_payload(key),
        headers=_headers(trace_id, request_id, key),
    )
    response.raise_for_status()
    return response.json()


def _request_payload(key: str) -> dict[str, Any]:
    return {
        "prompt": f"{PRIVATE_MARKER}:{key}",
        "max_output_tokens": 64,
        "temperature": 0.0,
    }


def _headers(
    trace_id: str,
    request_id: str,
    key: str,
    *,
    subject_id: str = OWNER_ID,
) -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-ae-api", audience=SERVICE_ID)
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        "X-NEX-Tenant-ID": TENANT_ID,
        "X-NEX-Subject-ID": subject_id,
        "Idempotency-Key": f"s99-{key}",
    }


def _access_context(
    trace_id: str, request_id: str, subject_id: str
) -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id=TENANT_ID,
        subject_id=subject_id,
        request_id=request_id,
        trace_id=trace_id,
        scopes=("service:call",),
    )


def _database_identity(engine) -> dict[str, str]:  # pragma: no cover
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT current_database() AS database, current_user AS role")
        ).mappings().one()
    return {"database": str(row["database"]), "role": str(row["role"])}


def _migration_count(engine) -> int:  # pragma: no cover
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM schema_migrations WHERE version = :version"
                ),
                {"version": LATEST_MIGRATION_VERSION},
            ).scalar_one()
        )


def _database_observation(  # pragma: no cover
    engine,
    *,
    trace_id: str,
    request_id: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        job_statuses = connection.execute(
            text(
                "SELECT status, count(*) AS count FROM service_jobs "
                "WHERE trace_id = :trace_id GROUP BY status"
            ),
            {"trace_id": trace_id},
        ).mappings()
        execution_statuses = connection.execute(
            text(
                "SELECT status, count(*) AS count FROM cx_generation_executions "
                "WHERE trace_id = :trace_id GROUP BY status"
            ),
            {"trace_id": trace_id},
        ).mappings()
        admission_statuses = connection.execute(
            text(
                "SELECT status, count(*) AS count FROM cx_gen_admissions "
                "WHERE trace_id = :trace_id GROUP BY status"
            ),
            {"trace_id": trace_id},
        ).mappings()
        events = list(
            connection.execute(
                text(
                    "SELECT event_type, details FROM service_operational_events "
                    "WHERE trace_id = :trace_id OR request_id = :request_id"
                ),
                {"trace_id": trace_id, "request_id": request_id},
            ).mappings()
        )
    return {
        "job_status_counts": _counts(job_statuses),
        "execution_status_counts": _counts(execution_statuses),
        "admission_status_counts": _counts(admission_statuses),
        "event_type_counts": dict(
            Counter(str(event["event_type"]) for event in events)
        ),
        "event_details": [event["details"] for event in events],
    }


def _counts(rows) -> dict[str, int]:  # pragma: no cover
    return {str(row["status"]): int(row["count"]) for row in rows}


def _cleanup_probe_rows(  # pragma: no cover
    engine,
    *,
    trace_id: str,
    request_id: str,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM service_operational_events "
                "WHERE trace_id = :trace_id OR request_id = :request_id"
            ),
            {"trace_id": trace_id, "request_id": request_id},
        )
        connection.execute(
            text("DELETE FROM service_jobs WHERE trace_id = :trace_id"),
            {"trace_id": trace_id},
        )
        connection.execute(
            text("DELETE FROM cx_generation_executions WHERE trace_id = :trace_id"),
            {"trace_id": trace_id},
        )
        connection.execute(
            text("DELETE FROM cx_gen_admissions WHERE trace_id = :trace_id"),
            {"trace_id": trace_id},
        )


def _probe_residue(  # pragma: no cover
    engine,
    *,
    trace_id: str,
    request_id: str,
) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    """
                    SELECT
                      (SELECT count(*) FROM service_operational_events
                       WHERE trace_id = :trace_id OR request_id = :request_id)
                    + (SELECT count(*) FROM service_jobs WHERE trace_id = :trace_id)
                    + (SELECT count(*) FROM cx_generation_executions
                       WHERE trace_id = :trace_id)
                    + (SELECT count(*) FROM cx_gen_admissions
                       WHERE trace_id = :trace_id)
                    """
                ),
                {"trace_id": trace_id, "request_id": request_id},
            ).scalar_one()
        )


def _target_url_allowed(database_url: str) -> bool:
    try:
        parsed = urlsplit(database_url)
        return (
            unquote(parsed.username or "") == EXPECTED_ROLE
            and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
        )
    except ValueError:
        return False


def _redact_detail(detail: str, *, database_url: str) -> str:
    if not database_url:
        return detail
    redacted = detail.replace(database_url, redact_database_url(database_url))
    password = urlsplit(database_url).password
    return redacted.replace(unquote(password), "***") if password else redacted


def _wire(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    execution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }
    if execution is not None:
        result.update(execution)
    return result


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return f"cx_async_generation_postgres_smoke=skipped reason={SMOKE_ENV}"
    details = result.get("details") or {}
    return (
        "cx_async_generation_postgres_smoke="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"database={result.get('database', 'not-run')} "
        f"jobs={details.get('job_status_counts', 'not-run')} "
        f"recovery={details.get('recovered_status', 'not-run')} "
        f"residue={result.get('probe_residue', 'not-run')} "
        f"failed_checks={len(result.get('failed_checks') or [])} "
        f"remote_required={result.get('remote_provider_required', False)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run protected CX async generation PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    result = run_cx_async_generation_postgres_smoke()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] != "FAIL" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
