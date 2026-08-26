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
CX_PATH = ROOT / "services" / "nex-cx"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(AG_PATH))
sys.path.insert(0, str(CX_PATH))

from nex_ag.generation_remediation import (  # noqa: E402
    SqlAlchemyGenerationRemediationTaskStore,
    build_generation_remediation_action,
)
from nex_ag.generation_remediation_execution import (  # noqa: E402
    AG_REMEDIATION_EXECUTION_STATUS_SYNC_SCHEMA_VERSION,
    register_generation_remediation_execution_routes,
)
from nex_ag.generation_remediation_handoff import (  # noqa: E402
    CxRemediationExecutionClientError,
)
from nex_cx.generation import GenerationExecutionStore  # noqa: E402
from nex_cx.remediation_execution import (  # noqa: E402
    CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION,
    CX_REMEDIATION_EXECUTION_REQUEST_SCHEMA_VERSION,
    SqlAlchemyRemediationExecutionStore,
    build_cx_remediation_execution_result,
    register_remediation_execution_routes,
)
from nex_runtime import (  # noqa: E402
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


SCHEMA_VERSION = "ag_remediation_execution_status_sync_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_REMEDIATION_EXECUTION_STATUS_SYNC_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AG_REMEDIATION_EXECUTION_STATUS_SYNC_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
AG_SERVICE_ID = "nex-ag"
CX_SERVICE_ID = "nex-cx"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
OBSERVED_AT = "2026-08-26T00:00:00Z"


class NoopCxRemediationExecutionClient:
    def submit_remediation_action(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("Status sync smoke must not dispatch a CX execution.")


class InProcessCxRemediationExecutionStatusClient:
    def __init__(self, client: TestClient) -> None:
        self._client = client
        self.call_count = 0
        self.last_path: str | None = None

    def get_remediation_execution_detail(
        self,
        *,
        parent_cx_generation_id: str,
        remediation_action_id: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        self.call_count += 1
        path = (
            f"/api/v1/generations/{parent_cx_generation_id}"
            f"/remediation-executions/{remediation_action_id}"
        )
        self.last_path = path
        response = self._client.get(
            path,
            headers=_cx_service_headers(
                request_id=request_id,
                trace_id=trace_id,
            ),
        )
        if response.status_code >= 400:
            problem = _safe_json(response)
            raise CxRemediationExecutionClientError(
                status_code=response.status_code,
                error_code=str(
                    problem.get("error_code")
                    or "ag.cx_remediation_execution_unavailable"
                ),
                detail=str(problem.get("detail") or "CX execution detail failed."),
                retryable=response.status_code >= 500,
            )
        return response.json()


def run_ag_remediation_execution_status_sync_postgres_smoke(
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
        ag_database_env = service_database_env(AG_SERVICE_ID, profile=profile)
        cx_database_env = service_database_env(CX_SERVICE_ID, profile=profile)
        ag_database_url = service_database_url(
            AG_SERVICE_ID,
            profile=profile,
            environ=env,
        )
        cx_database_url = service_database_url(
            CX_SERVICE_ID,
            profile=profile,
            environ=env,
        )
        ag_migration = run_service_migrations(
            AG_SERVICE_ID,
            database_url=ag_database_url,
            profile=profile,
        )
        cx_migration = run_service_migrations(
            CX_SERVICE_ID,
            database_url=cx_database_url,
            profile=profile,
        )
        execution = _execute_status_sync_smoke(
            ag_database_env=ag_database_env,
            ag_database_url=ag_database_url,
            cx_database_env=cx_database_env,
            cx_database_url=cx_database_url,
        )
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": AG_SERVICE_ID,
            "profile": profile,
            "ag_database_env": ag_database_env,
            "cx_database_env": cx_database_env,
            "redacted_ag_database_url": redact_database_url(ag_database_url),
            "redacted_cx_database_url": redact_database_url(cx_database_url),
            "migration": {
                AG_SERVICE_ID: _migration_evidence(ag_migration),
                CX_SERVICE_ID: _migration_evidence(cx_migration),
            },
            **execution,
        }
    except (MigrationError, ValueError) as exc:
        evidence = _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        evidence = _failure("execution_failed", exc.__class__.__name__, profile=profile)

    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _execute_status_sync_smoke(
    *,
    ag_database_env: str,
    ag_database_url: str,
    cx_database_env: str,
    cx_database_url: str,
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    request_id = f"ag-remediation-status-sync-smoke-{suffix}"
    action_id = f"ag-remediation-status-sync-{suffix}"
    generation_id = f"cx-gen-remediation-status-sync-{suffix}"
    repair_generation_id = f"cx-gen-remediation-repair-{suffix}"
    cx_result_ref_id = f"cx-repair-run-{suffix}"
    ag_engine = None
    cx_engine = None
    try:
        ag_engine = build_engine(ag_database_url)
        cx_engine = build_engine(cx_database_url)
        ag_store = SqlAlchemyGenerationRemediationTaskStore(
            build_session_factory(ag_engine),
            database_env=ag_database_env,
            redacted_database_url=redact_database_url(ag_database_url),
        )
        cx_store = SqlAlchemyRemediationExecutionStore(
            build_session_factory(cx_engine),
            database_env=cx_database_env,
            redacted_database_url=redact_database_url(cx_database_url),
        )
        ag_record = ag_store.save(
            _ag_remediation_record(
                suffix=suffix,
                request_id=request_id,
                action_id=action_id,
                generation_id=generation_id,
            )
        )
        cx_record = cx_store.save(
            _cx_execution_record(
                suffix=suffix,
                request_id=request_id,
                action_id=action_id,
                generation_id=generation_id,
                repair_generation_id=repair_generation_id,
                result_ref_id=cx_result_ref_id,
            )
        )
        cx_status_client = InProcessCxRemediationExecutionStatusClient(
            _build_cx_client(cx_store),
        )
        ag_client = _build_ag_client(
            ag_store=ag_store,
            cx_status_client=cx_status_client,
        )
        response = ag_client.post(
            (
                f"/admin/v1/generation-audit/generations/{generation_id}"
                f"/remediation-tasks/{action_id}/sync-execution-status"
            ),
            headers=_ag_service_headers(request_id=request_id),
            json={"observed_at": OBSERVED_AT},
        )
        response.raise_for_status()
        sync = response.json()
        final_record = ag_store.get(action_id)
        ag_observations = _ag_db_observations(
            ag_engine,
            remediation_action_id=action_id,
        )
        cx_observations = _cx_db_observations(
            cx_engine,
            remediation_action_id=action_id,
        )
        checks = {
            "ag_task_seeded": ag_record["action_status"] == "WAITING_ON_CX",
            "cx_execution_seeded": cx_record["execution_status"] == "SUCCEEDED",
            "route_ok": response.status_code == 200,
            "status_sync_schema": sync["status_sync_schema_version"]
            == AG_REMEDIATION_EXECUTION_STATUS_SYNC_SCHEMA_VERSION,
            "sync_updated": sync["sync_status"] == "UPDATED",
            "sync_completed": sync["final_action_status"] == "COMPLETED",
            "cx_detail_schema": sync["cx_detail_schema_version"]
            == CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION,
            "cx_status_client_called_once": cx_status_client.call_count == 1,
            "final_record_persisted": final_record is not None
            and final_record["action_status"] == "COMPLETED",
            "result_ref_round_tripped": final_record is not None
            and final_record["result_ref"]["ref_id"] == cx_result_ref_id,
            "ag_row_count": ag_observations["row_count"] == 1,
            "ag_row_status": ag_observations["action_status"] == "COMPLETED",
            "cx_row_count": cx_observations["row_count"] == 1,
            "cx_row_status": cx_observations["execution_status"] == "SUCCEEDED",
            "raw_payload_absent": _redaction_safe(
                {
                    "sync": sync,
                    "ag_observations": ag_observations,
                    "cx_observations": cx_observations,
                }
            ),
        }
        if not all(checks.values()):
            raise RuntimeError("AG remediation execution status sync smoke failed")
        return {
            "request_id": request_id,
            "trace_id": TRACE_ID,
            "remediation_action_id": action_id,
            "cx_generation_id": generation_id,
            "cx_status_client": {
                "mode": "in_process_cx_read_model",
                "call_count": cx_status_client.call_count,
                "last_path": cx_status_client.last_path,
            },
            "sync": {
                "status_sync_schema_version": sync["status_sync_schema_version"],
                "sync_status": sync["sync_status"],
                "cx_detail_schema_version": sync["cx_detail_schema_version"],
                "cx_execution_status": sync["cx_execution_status"],
                "previous_action_status": sync["previous_action_status"],
                "final_action_status": sync["final_action_status"],
                "status_update_count": sync["status_update_count"],
            },
            "observations": {
                AG_SERVICE_ID: ag_observations,
                CX_SERVICE_ID: cx_observations,
            },
            "checks": checks,
            "cleanup": {
                AG_SERVICE_ID: _cleanup_ag_smoke_rows(
                    ag_engine,
                    remediation_action_id=action_id,
                ),
                CX_SERVICE_ID: _cleanup_cx_smoke_rows(
                    cx_engine,
                    remediation_action_id=action_id,
                ),
            },
        }
    finally:
        if ag_engine is not None:
            _cleanup_ag_smoke_rows(ag_engine, remediation_action_id=action_id)
            ag_engine.dispose()
        if cx_engine is not None:
            _cleanup_cx_smoke_rows(cx_engine, remediation_action_id=action_id)
            cx_engine.dispose()


def _build_ag_client(
    *,
    ag_store: Any,
    cx_status_client: InProcessCxRemediationExecutionStatusClient,
) -> TestClient:
    app = build_service_app(SERVICE_SPECS[AG_SERVICE_ID])
    register_generation_remediation_execution_routes(
        app,
        store=ag_store,
        cx_client=NoopCxRemediationExecutionClient(),
        cx_status_client=cx_status_client,
    )
    return TestClient(app)


def _build_cx_client(cx_store: Any) -> TestClient:
    app = build_service_app(SERVICE_SPECS[CX_SERVICE_ID])
    register_remediation_execution_routes(
        app,
        generation_store=GenerationExecutionStore(),
        execution_store=cx_store,
    )
    return TestClient(app)


def _ag_remediation_record(
    *,
    suffix: str,
    request_id: str,
    action_id: str,
    generation_id: str,
) -> dict[str, Any]:
    return build_generation_remediation_action(
        {
            "remediation_action_id": action_id,
            "tenant_id": f"tenant-status-sync-smoke-{suffix}",
            "action_type": "citation_repair",
            "action_status": "WAITING_ON_CX",
            "priority": "HIGH",
            "reason_codes": ["citation_quality", "operator_requested_repair"],
            "owner_ref": {
                "owner_type": "service",
                "owner_id": AG_SERVICE_ID,
                "tenant_id": f"tenant-status-sync-smoke-{suffix}",
            },
            "source_refs": [
                {
                    "source_service": AG_SERVICE_ID,
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


def _cx_execution_record(
    *,
    suffix: str,
    request_id: str,
    action_id: str,
    generation_id: str,
    repair_generation_id: str,
    result_ref_id: str,
) -> dict[str, Any]:
    record = build_cx_remediation_execution_result(
        _cx_remediation_request_payload(
            suffix=suffix,
            request_id=request_id,
            action_id=action_id,
            generation_id=generation_id,
        ),
        request_id=request_id,
        trace_id=TRACE_ID,
        created_at=OBSERVED_AT,
    )
    record.update(
        {
            "repair_cx_generation_id": repair_generation_id,
            "execution_status": "SUCCEEDED",
            "result_ref": {
                "source_service": CX_SERVICE_ID,
                "ref_type": "repair_execution",
                "ref_id": result_ref_id,
                "relation": "result_of",
            },
            "updated_at": OBSERVED_AT,
        }
    )
    return record


def _cx_remediation_request_payload(
    *,
    suffix: str,
    request_id: str,
    action_id: str,
    generation_id: str,
) -> dict[str, Any]:
    return {
        "request_schema_version": CX_REMEDIATION_EXECUTION_REQUEST_SCHEMA_VERSION,
        "remediation_action_id": action_id,
        "parent_cx_generation_id": generation_id,
        "tenant_id": f"tenant-status-sync-smoke-{suffix}",
        "trace_id": TRACE_ID,
        "request_id": request_id,
        "action_type": "citation_repair",
        "lineage_type": "repair",
        "reason_codes": ["citation_quality", "postgres_status_sync_smoke"],
        "source_refs": [
            {
                "source_service": AG_SERVICE_ID,
                "ref_type": "generation_remediation_task",
                "ref_id": action_id,
                "relation": "requested_by",
            }
        ],
        "evidence": {
            "evidence_hashes": ["a" * 64],
            "raw_evidence_stored": False,
        },
        "execution_policy": {
            "parent_generation_mutation_allowed": False,
            "retrieval_package_policy": "reuse_or_expand_cited_evidence",
            "prompt_package_policy": "rebuild_with_citation_repair_instruction_ref",
            "provider_boundary": "cx_to_mo_service_api_only",
        },
        "idempotency_key": f"cx-remediation-status-sync-smoke-{suffix}",
    }


def _ag_service_headers(*, request_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience=AG_SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _cx_service_headers(
    *,
    request_id: str | None,
    trace_id: str | None,
) -> dict[str, str]:
    issued = issue_mock_service_token(service_id=AG_SERVICE_ID, audience=CX_SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id or f"ag-remediation-status-sync-{uuid4().hex}",
        "traceparent": f"00-{trace_id or TRACE_ID}-00f067aa0ba902b7-01",
    }


def _safe_json(response: Any) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _ag_db_observations(engine: Any, *, remediation_action_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(*) AS row_count,
                        max(action_status) AS action_status,
                        max(result_ref->>'ref_id') AS result_ref_id,
                        pg_typeof(result_ref)::text AS result_ref_type
                    FROM ag_generation_remediation_tasks
                    WHERE remediation_action_id = :remediation_action_id
                    GROUP BY pg_typeof(result_ref)::text
                    """
                ),
                {"remediation_action_id": remediation_action_id},
            )
            .mappings()
            .first()
        )
    return {
        "row_count": int(row["row_count"]) if row else 0,
        "action_status": row["action_status"] if row else None,
        "result_ref_id": row["result_ref_id"] if row else None,
        "result_ref_type": row["result_ref_type"] if row else None,
    }


def _cx_db_observations(engine: Any, *, remediation_action_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(*) AS row_count,
                        max(execution_status) AS execution_status,
                        max(parent_cx_generation_id) AS parent_cx_generation_id,
                        max(result_ref->>'ref_id') AS result_ref_id,
                        pg_typeof(result_ref)::text AS result_ref_type
                    FROM cx_remediation_execution_attempts
                    WHERE remediation_action_id = :remediation_action_id
                    GROUP BY pg_typeof(result_ref)::text
                    """
                ),
                {"remediation_action_id": remediation_action_id},
            )
            .mappings()
            .first()
        )
    return {
        "row_count": int(row["row_count"]) if row else 0,
        "execution_status": row["execution_status"] if row else None,
        "parent_cx_generation_id": row["parent_cx_generation_id"] if row else None,
        "result_ref_id": row["result_ref_id"] if row else None,
        "result_ref_type": row["result_ref_type"] if row else None,
    }


def _cleanup_ag_smoke_rows(engine: Any, *, remediation_action_id: str) -> dict[str, int]:
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


def _cleanup_cx_smoke_rows(engine: Any, *, remediation_action_id: str) -> dict[str, int]:
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    DELETE FROM cx_remediation_execution_attempts
                    WHERE remediation_action_id = :remediation_action_id
                    """
                ),
                {"remediation_action_id": remediation_action_id},
            )
    except SQLAlchemyError:
        return {"cx_remediation_execution_attempts": 0}
    return {"cx_remediation_execution_attempts": _rowcount(result)}


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
        "service_id": AG_SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    for service_id in (AG_SERVICE_ID, CX_SERVICE_ID):
        raw_url = environ.get(service_database_env(service_id, profile="test"))
        if raw_url and raw_url in serialized_evidence:
            raise ValueError(
                "AG remediation execution status sync smoke contains raw DB URL."
            )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ag_remediation_execution_status_sync_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ag_remediation_execution_status_sync_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"ag_db_env={evidence['ag_database_env']} "
            f"cx_db_env={evidence['cx_database_env']} "
            f"final_status={evidence['sync']['final_action_status']} "
            f"cx_status={evidence['sync']['cx_execution_status']} "
            "cleanup_ag="
            f"{evidence['cleanup'][AG_SERVICE_ID]['ag_generation_remediation_tasks']} "
            "cleanup_cx="
            f"{evidence['cleanup'][CX_SERVICE_ID]['cx_remediation_execution_attempts']}"
        )
    return (
        "ag_remediation_execution_status_sync_postgres_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AG remediation execution status-sync PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ag_remediation_execution_status_sync_postgres_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, default=str)
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
