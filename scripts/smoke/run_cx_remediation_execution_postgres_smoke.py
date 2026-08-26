#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
CX_PATH = ROOT / "services" / "nex-cx"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(CX_PATH))

from nex_cx.generation import GenerationExecutionStore  # noqa: E402
from nex_cx.remediation_execution import (  # noqa: E402
    CX_REMEDIATION_EXECUTION_JOB_TYPE,
    CX_REMEDIATION_EXECUTION_REQUEST_SCHEMA_VERSION,
    RemediationExecutionError,
    SqlAlchemyRemediationExecutionStore,
    build_cx_remediation_execution_result,
    enqueue_remediation_execution_job,
    remediation_execution_job_id,
)
from nex_cx.remediation_execution_worker import (  # noqa: E402
    CX_REMEDIATION_EXECUTION_WORKER_ID,
    repair_generation_id_for_action,
    run_cx_remediation_execution_worker_once,
)
from nex_runtime import (  # noqa: E402
    JobQueueError,
    SERVICE_SPECS,
    SqlAlchemyJobQueue,
    build_engine,
    build_session_factory,
    load_env_file,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SCHEMA_VERSION = "cx_remediation_execution_postgres_smoke.v1"
SMOKE_ENV = "NEX_CX_REMEDIATION_EXECUTION_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_CX_REMEDIATION_EXECUTION_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SERVICE_SPEC = SERVICE_SPECS[SERVICE_ID]
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
OBSERVED_AT = "2026-08-26T00:00:00Z"
EXPECTED_EXECUTION_JSONB_COLUMNS = {
    "result_ref": "jsonb",
    "failure": "jsonb",
    "redaction_summary": "jsonb",
    "metadata": "jsonb",
}
EXPECTED_EXECUTION_INDEXES = {
    "idx_cx_remediation_execution_parent_updated",
    "idx_cx_remediation_execution_root_updated",
    "idx_cx_remediation_execution_trace",
    "idx_cx_remediation_execution_status_updated",
    "idx_cx_remediation_execution_repair_generation",
}
EXPECTED_SERVICE_JOB_INDEXES = {
    "ix_service_jobs_status_available",
    "ix_service_jobs_type_status",
    "ix_service_jobs_trace",
    "ix_service_jobs_subject",
}


def run_cx_remediation_execution_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    if profile != "test":
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        migration_result = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_remediation_execution_smoke(
            database_env=database_env,
            database_url=database_url,
        )
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            "migration": _migration_evidence(migration_result),
            **execution,
        }
    except (MigrationError, ValueError) as exc:
        evidence = _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        evidence = _failure("execution_failed", exc.__class__.__name__, profile=profile)

    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _execute_remediation_execution_smoke(
    *,
    database_env: str,
    database_url: str,
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    request_id = f"cx-remediation-execution-smoke-{suffix}"
    action_id = f"ag-remediation-action-smoke-{suffix}"
    parent_id = f"cx-gen-remediation-parent-{suffix}"
    job_id = remediation_execution_job_id(action_id)
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    execution_store = SqlAlchemyRemediationExecutionStore(
        session_factory,
        database_env=database_env,
        redacted_database_url=redact_database_url(database_url),
    )
    job_queue = SqlAlchemyJobQueue(session_factory)
    generation_store = GenerationExecutionStore()

    try:
        request_payload = _remediation_request_payload(
            suffix=suffix,
            request_id=request_id,
            action_id=action_id,
            parent_id=parent_id,
        )
        accepted = build_cx_remediation_execution_result(
            request_payload,
            request_id=request_id,
            trace_id=TRACE_ID,
            created_at=OBSERVED_AT,
        )
        generation_store.save(_parent_generation_record(parent_id, request_id=request_id))
        saved = execution_store.save(accepted)
        loaded = execution_store.get(action_id)
        if loaded is None:
            raise RuntimeError("persisted remediation execution record was not found")
        listed_before = execution_store.list_for_parent(parent_id)
        queued = enqueue_remediation_execution_job(
            job_queue,
            execution_record=loaded,
            request_payload=request_payload,
        )
        worker_execution = run_cx_remediation_execution_worker_once(
            job_queue=job_queue,
            generation_store=generation_store,
            execution_store=execution_store,
            worker_id=CX_REMEDIATION_EXECUTION_WORKER_ID,
            clock=lambda: OBSERVED_AT,
        )
        final_job = job_queue.get_job(job_id)
        final_record = execution_store.get(action_id)
        listed_after = execution_store.list_for_parent(parent_id)
        repair_id = repair_generation_id_for_action(action_id)
        repair_record = generation_store.get(repair_id)
        observations = _db_observations(
            engine,
            remediation_action_id=action_id,
            job_id=job_id,
        )
        checks = {
            "accepted_saved": saved["execution_status"] == "ACCEPTED",
            "accepted_loaded_from_postgres": loaded["remediation_action_id"] == action_id,
            "listed_before_worker": [item["remediation_action_id"] for item in listed_before]
            == [action_id],
            "job_enqueued_to_postgres": queued["job_id"] == job_id
            and queued["status"] == "QUEUED",
            "worker_succeeded": worker_execution.status == "SUCCEEDED",
            "worker_handler_succeeded": (
                worker_execution.handler_result is not None
                and worker_execution.handler_result.get("execution_status") == "SUCCEEDED"
            ),
            "final_job_succeeded": final_job is not None
            and final_job["status"] == "SUCCEEDED"
            and final_job["attempt_count"] == 1,
            "final_execution_succeeded": final_record is not None
            and final_record["execution_status"] == "SUCCEEDED",
            "repair_generation_created": repair_record is not None
            and repair_record["cx_generation_id"] == repair_id
            and repair_record["parent_cx_generation_id"] == parent_id,
            "parent_generation_unchanged": generation_store.get(parent_id)
            == _parent_generation_record(parent_id, request_id=request_id),
            "listed_after_worker": [
                item["remediation_action_id"] for item in listed_after
            ]
            == [action_id],
            "execution_row_observed": (
                observations["remediation_execution_attempt"]["row_count"] == 1
            ),
            "execution_jsonb_columns": (
                observations["remediation_execution_attempt"]["jsonb_columns"]
                == EXPECTED_EXECUTION_JSONB_COLUMNS
            ),
            "execution_indexes_present": EXPECTED_EXECUTION_INDEXES.issubset(
                set(observations["remediation_execution_attempt"]["index_names"])
            ),
            "service_job_row_observed": observations["service_job"]["row_count"] == 1,
            "service_job_payload_jsonb": (
                observations["service_job"]["payload_type"] == "jsonb"
            ),
            "service_job_indexes_present": EXPECTED_SERVICE_JOB_INDEXES.issubset(
                set(observations["service_job"]["index_names"])
            ),
        }
        if not all(checks.values()):
            raise RuntimeError("CX remediation execution PostgreSQL smoke checks failed")
        return {
            "request_id": request_id,
            "trace_id": TRACE_ID,
            "remediation_action_id": action_id,
            "parent_cx_generation_id": parent_id,
            "repair_cx_generation_id": repair_id,
            "job_id": job_id,
            "worker": worker_execution.to_summary(),
            "observations": observations,
            "checks": checks,
            "cleanup": _cleanup_smoke_rows(
                engine,
                remediation_action_id=action_id,
                job_id=job_id,
                trace_id=TRACE_ID,
                request_id=request_id,
            ),
        }
    except (RemediationExecutionError, JobQueueError, SQLAlchemyError, RuntimeError) as exc:
        _cleanup_smoke_rows(
            engine,
            remediation_action_id=action_id,
            job_id=job_id,
            trace_id=TRACE_ID,
            request_id=request_id,
        )
        raise RuntimeError(str(exc) or exc.__class__.__name__) from exc
    finally:
        engine.dispose()


def _remediation_request_payload(
    *,
    suffix: str,
    request_id: str,
    action_id: str,
    parent_id: str,
) -> dict[str, Any]:
    return {
        "request_schema_version": CX_REMEDIATION_EXECUTION_REQUEST_SCHEMA_VERSION,
        "remediation_action_id": action_id,
        "parent_cx_generation_id": parent_id,
        "tenant_id": f"tenant-remediation-smoke-{suffix}",
        "trace_id": TRACE_ID,
        "request_id": request_id,
        "action_type": "citation_repair",
        "lineage_type": "repair",
        "reason_codes": ["citation_quality", "postgres_smoke"],
        "source_refs": [
            {
                "source_service": "nex-ag",
                "ref_type": "generation_remediation_task",
                "ref_id": f"ag-remediation-task-{suffix}",
                "relation": "requested_by",
            }
        ],
        "evidence": {
            "evidence_hashes": [
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ],
            "raw_evidence_stored": False,
        },
        "execution_policy": {
            "parent_generation_mutation_allowed": False,
            "retrieval_package_policy": "reuse_or_expand_cited_evidence",
            "prompt_package_policy": "rebuild_with_citation_repair_instruction_ref",
            "provider_boundary": "cx_to_mo_service_api_only",
        },
        "idempotency_key": f"cx-remediation-execution-smoke-{suffix}",
    }


def _parent_generation_record(parent_id: str, *, request_id: str) -> dict[str, Any]:
    return {
        "record_schema_version": "cx_generation_execution_record.v1",
        "cx_generation_id": parent_id,
        "status": "COMPLETED",
        "trace_id": TRACE_ID,
        "request_id": request_id,
        "request_metadata": {
            "raw_prompt_stored": False,
            "raw_source_document_text_stored": False,
        },
        "response_metadata": {
            "output_hash": "0" * 64,
            "output_preview": None,
        },
        "created_at": OBSERVED_AT,
        "updated_at": OBSERVED_AT,
    }


def _db_observations(
    engine: Any,
    *,
    remediation_action_id: str,
    job_id: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        execution_row = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(*) AS row_count,
                        max(execution_status) AS execution_status,
                        max(attempt_no) AS attempt_no,
                        max(repair_cx_generation_id) AS repair_cx_generation_id,
                        pg_typeof(result_ref)::text AS result_ref_type,
                        pg_typeof(failure)::text AS failure_type,
                        pg_typeof(redaction_summary)::text AS redaction_summary_type,
                        pg_typeof(metadata)::text AS metadata_type
                    FROM cx_remediation_execution_attempts
                    WHERE remediation_action_id = :remediation_action_id
                    GROUP BY
                        pg_typeof(result_ref)::text,
                        pg_typeof(failure)::text,
                        pg_typeof(redaction_summary)::text,
                        pg_typeof(metadata)::text
                    """
                ),
                {"remediation_action_id": remediation_action_id},
            )
            .mappings()
            .first()
        )
        execution_indexes = _index_names(
            connection,
            table_name="cx_remediation_execution_attempts",
        )
        job_row = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(*) AS row_count,
                        max(status) AS status,
                        max(job_type) AS job_type,
                        max(subject_type) AS subject_type,
                        max(subject_id) AS subject_id,
                        max(attempt_count) AS attempt_count,
                        max(max_attempts) AS max_attempts,
                        bool_or(completed_at IS NOT NULL) AS completed_at_present,
                        bool_or(locked_by IS NULL) AS lock_released,
                        pg_typeof(payload)::text AS payload_type,
                        max(payload->>'remediation_action_id') AS payload_action_id
                    FROM service_jobs
                    WHERE job_id = :job_id
                    GROUP BY pg_typeof(payload)::text
                    """
                ),
                {"job_id": job_id},
            )
            .mappings()
            .first()
        )
        job_indexes = _index_names(connection, table_name="service_jobs")
    return {
        "remediation_execution_attempt": {
            **_execution_observation(execution_row),
            "index_names": execution_indexes,
        },
        "service_job": {
            **_service_job_observation(job_row),
            "index_names": job_indexes,
        },
    }


def _index_names(connection: Any, *, table_name: str) -> list[str]:
    rows = (
        connection.execute(
            text(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename = :table_name
                """
            ),
            {"table_name": table_name},
        )
        .mappings()
        .all()
    )
    return sorted(row["indexname"] for row in rows)


def _execution_observation(row: Mapping[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {
            "row_count": 0,
            "execution_status": None,
            "attempt_no": None,
            "repair_cx_generation_id": None,
            "jsonb_columns": {
                "result_ref": None,
                "failure": None,
                "redaction_summary": None,
                "metadata": None,
            },
        }
    return {
        "row_count": int(row["row_count"]),
        "execution_status": row["execution_status"],
        "attempt_no": int(row["attempt_no"]),
        "repair_cx_generation_id": row["repair_cx_generation_id"],
        "jsonb_columns": {
            "result_ref": row["result_ref_type"],
            "failure": row["failure_type"],
            "redaction_summary": row["redaction_summary_type"],
            "metadata": row["metadata_type"],
        },
    }


def _service_job_observation(row: Mapping[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {
            "row_count": 0,
            "status": None,
            "job_type": None,
            "subject_type": None,
            "subject_id": None,
            "attempt_count": None,
            "max_attempts": None,
            "completed_at_present": False,
            "lock_released": False,
            "payload_type": None,
            "payload_action_id": None,
        }
    return {
        "row_count": int(row["row_count"]),
        "status": row["status"],
        "job_type": row["job_type"],
        "subject_type": row["subject_type"],
        "subject_id": row["subject_id"],
        "attempt_count": int(row["attempt_count"]),
        "max_attempts": int(row["max_attempts"]),
        "completed_at_present": bool(row["completed_at_present"]),
        "lock_released": bool(row["lock_released"]),
        "payload_type": row["payload_type"],
        "payload_action_id": row["payload_action_id"],
    }


def _cleanup_smoke_rows(
    engine: Any,
    *,
    remediation_action_id: str,
    job_id: str,
    trace_id: str,
    request_id: str,
) -> dict[str, int]:
    try:
        with engine.begin() as connection:
            job_result = connection.execute(
                text(
                    """
                    DELETE FROM service_jobs
                    WHERE job_id = :job_id
                       OR (
                            job_type = :job_type
                        AND trace_id = :trace_id
                        AND request_id = :request_id
                       )
                    """
                ),
                {
                    "job_id": job_id,
                    "job_type": CX_REMEDIATION_EXECUTION_JOB_TYPE,
                    "trace_id": trace_id,
                    "request_id": request_id,
                },
            )
            attempt_result = connection.execute(
                text(
                    """
                    DELETE FROM cx_remediation_execution_attempts
                    WHERE remediation_action_id = :remediation_action_id
                    """
                ),
                {"remediation_action_id": remediation_action_id},
            )
    except SQLAlchemyError:
        return {
            "service_jobs": 0,
            "cx_remediation_execution_attempts": 0,
        }
    return {
        "service_jobs": _rowcount(job_result),
        "cx_remediation_execution_attempts": _rowcount(attempt_result),
    }


def _rowcount(result: Any) -> int:
    value = getattr(result, "rowcount", 0)
    return int(value) if isinstance(value, int) and value > 0 else 0


def _migration_evidence(result: Any) -> dict[str, list[str] | bool | str]:
    return {
        "service_id": result.service_id,
        "profile": result.profile,
        "dry_run": result.dry_run,
        "planned": list(result.planned),
        "applied": list(result.applied),
        "skipped": list(result.skipped),
    }


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    for key in (
        service_database_env(SERVICE_ID, profile="test"),
        SERVICE_SPEC.database_env,
    ):
        raw_url = environ.get(key)
        if raw_url and raw_url in serialized_evidence:
            raise ValueError("CX remediation execution smoke evidence contains raw database URL.")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"cx_remediation_execution_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "cx_remediation_execution_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"job_status={evidence['observations']['service_job']['status']} "
            f"execution_status="
            f"{evidence['observations']['remediation_execution_attempt']['execution_status']} "
            f"cleanup_jobs={evidence['cleanup']['service_jobs']} "
            f"cleanup_attempts={evidence['cleanup']['cx_remediation_execution_attempts']}"
        )
    return (
        "cx_remediation_execution_postgres_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional CX remediation execution PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_cx_remediation_execution_postgres_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, default=str)
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
