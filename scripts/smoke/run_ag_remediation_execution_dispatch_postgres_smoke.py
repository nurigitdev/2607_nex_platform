#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.generation_remediation import (  # noqa: E402
    SqlAlchemyGenerationRemediationTaskStore,
    build_generation_remediation_action,
    register_generation_remediation_task_routes,
)
from nex_ag.generation_remediation_execution import (  # noqa: E402
    AG_REMEDIATION_EXECUTION_DISPATCH_SCHEMA_VERSION,
    register_generation_remediation_execution_routes,
)
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    SERVICE_SPECS,
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


SCHEMA_VERSION = "ag_remediation_execution_dispatch_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_REMEDIATION_EXECUTION_DISPATCH_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AG_REMEDIATION_EXECUTION_DISPATCH_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-ag"
SERVICE_SPEC = SERVICE_SPECS[SERVICE_ID]
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
OBSERVED_AT = "2026-08-26T00:00:00Z"
EXPECTED_JSONB_COLUMNS = {
    "owner_ref": "jsonb",
    "reason_codes": "jsonb",
    "source_refs": "jsonb",
    "evidence": "jsonb",
    "result_ref": "jsonb",
    "metadata": "jsonb",
}
EXPECTED_INDEXES = {
    "idx_ag_generation_remediation_tasks_generation_time",
    "idx_ag_generation_remediation_tasks_status_time",
    "idx_ag_generation_remediation_tasks_type_time",
    "idx_ag_generation_remediation_tasks_owner_time",
}


class StaticCxRemediationExecutionClient:
    def __init__(self) -> None:
        self.call_count = 0
        self.last_action_id: str | None = None
        self.last_idempotency_key: str | None = None

    def submit_remediation_action(
        self,
        action: Mapping[str, Any],
        *,
        request_id: str | None = None,
        trace_id: str | None = None,
        requested_at: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.call_count += 1
        self.last_action_id = str(action["remediation_action_id"])
        self.last_idempotency_key = idempotency_key
        return {
            "result_schema_version": "cx_remediation_execution_result.v1",
            "remediation_action_id": action["remediation_action_id"],
            "parent_cx_generation_id": action["cx_generation_id"],
            "repair_cx_generation_id": None,
            "tenant_id": action.get("tenant_id"),
            "trace_id": trace_id or action["trace_id"],
            "request_id": request_id or action["request_id"],
            "action_type": action["action_type"],
            "lineage_type": "repair",
            "execution_status": "ACCEPTED",
            "result_ref": None,
            "failure": None,
            "redaction_summary": {
                "raw_content_included": False,
                "prompt_text_included": False,
                "evidence_text_included": False,
                "provider_detail_included": False,
            },
            "created_at": requested_at or OBSERVED_AT,
            "updated_at": requested_at or OBSERVED_AT,
        }


def run_ag_remediation_execution_dispatch_postgres_smoke(
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
        execution = _execute_dispatch_smoke(
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


def _execute_dispatch_smoke(
    *,
    database_env: str,
    database_url: str,
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    request_id = f"ag-remediation-execution-dispatch-smoke-{suffix}"
    action_id = f"ag-remediation-dispatch-smoke-{suffix}"
    generation_id = f"cx-gen-remediation-dispatch-smoke-{suffix}"
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    store = SqlAlchemyGenerationRemediationTaskStore(
        session_factory,
        database_env=database_env,
        redacted_database_url=redact_database_url(database_url),
    )
    cx_client = StaticCxRemediationExecutionClient()
    app = build_service_app(SERVICE_SPEC)
    register_generation_remediation_task_routes(
        app,
        store=store,
        audit_event_store=InMemoryOperationalEventStore(),
    )
    register_generation_remediation_execution_routes(
        app,
        store=store,
        cx_client=cx_client,
    )
    client = TestClient(app)

    try:
        created = store.save(
            build_generation_remediation_action(
                {
                    "remediation_action_id": action_id,
                    "tenant_id": f"tenant-dispatch-smoke-{suffix}",
                    "action_type": "citation_repair",
                    "action_status": "PROPOSED",
                    "priority": "HIGH",
                    "reason_codes": ["citation_quality", "operator_requested_repair"],
                    "owner_ref": {
                        "owner_type": "service",
                        "owner_id": "nex-ag",
                        "tenant_id": f"tenant-dispatch-smoke-{suffix}",
                    },
                    "source_refs": [
                        {
                            "source_service": "nex-ag",
                            "ref_type": "generation_quality",
                            "ref_id": generation_id,
                            "relation": "caused_by",
                        }
                    ],
                    "evidence_hashes": ["a" * 64],
                    "evidence_previews": ["citation quality failed"],
                },
                cx_generation_id=generation_id,
                request_id=request_id,
                trace_id=TRACE_ID,
                created_at=OBSERVED_AT,
            )
        )
        response = client.post(
            (
                f"/admin/v1/generation-audit/generations/{generation_id}"
                f"/remediation-tasks/{action_id}/execute"
            ),
            headers=_service_headers(request_id=request_id),
            json={
                "requested_at": OBSERVED_AT,
                "planned_at": OBSERVED_AT,
                "idempotency_key": f"ag-remediation-dispatch-smoke-{suffix}",
            },
        )
        response.raise_for_status()
        dispatch = response.json()
        final_record = store.get(action_id)
        observations = _db_observations(engine, remediation_action_id=action_id)
        checks = {
            "task_seeded": created["action_status"] == "PROPOSED",
            "route_accepted": response.status_code == 202,
            "dispatch_schema": dispatch["dispatch_schema_version"]
            == AG_REMEDIATION_EXECUTION_DISPATCH_SCHEMA_VERSION,
            "dispatch_waiting_on_cx": dispatch["final_action_status"] == "WAITING_ON_CX",
            "cx_client_called_once": cx_client.call_count == 1,
            "final_record_persisted": final_record is not None
            and final_record["action_status"] == "WAITING_ON_CX",
            "result_ref_round_tripped": final_record is not None
            and final_record["result_ref"] == {
                "source_service": "nex-cx",
                "ref_type": "repair_execution",
                "ref_id": action_id,
                "relation": "result_of",
            },
            "row_count": observations["row_count"] == 1,
            "row_status": observations["action_status"] == "WAITING_ON_CX",
            "jsonb_columns": observations["jsonb_columns"] == EXPECTED_JSONB_COLUMNS,
            "indexes_present": EXPECTED_INDEXES.issubset(
                set(observations["index_names"])
            ),
            "raw_payload_absent": _redaction_safe(
                {
                    "dispatch": dispatch,
                    "observations": observations,
                }
            ),
        }
        if not all(checks.values()):
            raise RuntimeError("AG remediation execution dispatch PostgreSQL smoke failed")
        return {
            "request_id": request_id,
            "trace_id": TRACE_ID,
            "remediation_action_id": action_id,
            "cx_generation_id": generation_id,
            "cx_client": {
                "mode": "static",
                "call_count": cx_client.call_count,
                "last_action_id": cx_client.last_action_id,
                "last_idempotency_key_present": cx_client.last_idempotency_key
                is not None,
            },
            "dispatch": {
                "dispatch_schema_version": dispatch["dispatch_schema_version"],
                "dispatch_status": dispatch["dispatch_status"],
                "final_action_status": dispatch["final_action_status"],
                "status_update_count": dispatch["status_update_count"],
            },
            "observations": observations,
            "checks": checks,
            "cleanup": _cleanup_smoke_rows(engine, remediation_action_id=action_id),
        }
    finally:
        _cleanup_smoke_rows(engine, remediation_action_id=action_id)
        engine.dispose()


def _service_headers(*, request_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience=SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _db_observations(engine: Any, *, remediation_action_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(*) AS row_count,
                        max(action_status) AS action_status,
                        max(result_ref->>'ref_id') AS result_ref_id,
                        pg_typeof(owner_ref)::text AS owner_ref_type,
                        pg_typeof(reason_codes)::text AS reason_codes_type,
                        pg_typeof(source_refs)::text AS source_refs_type,
                        pg_typeof(evidence)::text AS evidence_type,
                        pg_typeof(result_ref)::text AS result_ref_type,
                        pg_typeof(metadata)::text AS metadata_type
                    FROM ag_generation_remediation_tasks
                    WHERE remediation_action_id = :remediation_action_id
                    GROUP BY
                        pg_typeof(owner_ref)::text,
                        pg_typeof(reason_codes)::text,
                        pg_typeof(source_refs)::text,
                        pg_typeof(evidence)::text,
                        pg_typeof(result_ref)::text,
                        pg_typeof(metadata)::text
                    """
                ),
                {"remediation_action_id": remediation_action_id},
            )
            .mappings()
            .first()
        )
        index_rows = (
            connection.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = 'ag_generation_remediation_tasks'
                    """
                )
            )
            .mappings()
            .all()
        )
    return {
        "row_count": int(row["row_count"]) if row else 0,
        "action_status": row["action_status"] if row else None,
        "result_ref_id": row["result_ref_id"] if row else None,
        "jsonb_columns": {
            "owner_ref": row["owner_ref_type"] if row else None,
            "reason_codes": row["reason_codes_type"] if row else None,
            "source_refs": row["source_refs_type"] if row else None,
            "evidence": row["evidence_type"] if row else None,
            "result_ref": row["result_ref_type"] if row else None,
            "metadata": row["metadata_type"] if row else None,
        },
        "index_names": sorted(row["indexname"] for row in index_rows),
    }


def _cleanup_smoke_rows(engine: Any, *, remediation_action_id: str) -> dict[str, int]:
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    DELETE FROM ag_generation_remediation_tasks
                    WHERE remediation_action_id = :remediation_action_id
                    """
                ),
                {"remediation_action_id": remediation_action_id},
            )
    except SQLAlchemyError:
        return {"ag_generation_remediation_tasks": 0}
    return {"ag_generation_remediation_tasks": _rowcount(result)}


def _rowcount(result: Any) -> int:
    value = getattr(result, "rowcount", 0)
    return int(value) if isinstance(value, int) and value > 0 else 0


def _redaction_safe(payload: Mapping[str, Any]) -> bool:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    forbidden = (
        '"raw_prompt":',
        '"raw_generation_output":',
        '"raw_source_document_text":',
        "do not persist raw",
        "hidden prompt",
        "provider_url",
        "provider_endpoint",
        "api_key",
        "password",
        "secret",
    )
    return all(fragment not in serialized for fragment in forbidden)


def _migration_evidence(result: Any) -> dict[str, list[str] | bool | str]:
    return {
        "service_id": result.service_id,
        "profile": result.profile,
        "dry_run": result.dry_run,
        "planned": list(result.planned),
        "applied": list(result.applied),
        "skipped": list(result.skipped),
    }


def _failure(failure_code: str, detail: str, *, profile: str) -> dict[str, Any]:
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
    raw_url = environ.get(service_database_env(SERVICE_ID, profile="test"))
    if raw_url and raw_url in serialized_evidence:
        raise ValueError("AG remediation execution dispatch smoke contains raw DB URL.")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ag_remediation_execution_dispatch_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ag_remediation_execution_dispatch_postgres_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']} "
            f"final_status={evidence['dispatch']['final_action_status']} "
            f"row_status={evidence['observations']['action_status']} "
            f"cleanup={evidence['cleanup']['ag_generation_remediation_tasks']}"
        )
    return (
        "ag_remediation_execution_dispatch_postgres_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AG remediation execution dispatch PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ag_remediation_execution_dispatch_postgres_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, default=str)
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
