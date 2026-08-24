#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator, ValidationError
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.generation_audit import build_generation_audit_projection  # noqa: E402
from nex_ag.operations import (  # noqa: E402
    build_generation_quality_issue_detail_projection,
    build_operations_dashboard_snapshot_projection,
    build_operations_issue_candidate_projection,
)
from nex_runtime import (  # noqa: E402
    InMemoryJobQueue,
    InMemoryServiceLogStore,
    SqlAlchemyOperationalEventStore,
    build_engine,
    build_operational_event,
    build_session_factory,
    database_pool_settings,
    load_env_file,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)

SMOKE_ENV = "NEX_AG_GENERATION_QUALITY_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AG_GENERATION_QUALITY_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-ag"
SCHEMA_VERSION = "ag_generation_quality_postgres_smoke.v1"
EVENT_TYPE = "ag.generation_quality.smoke"
CREATED_AT = "2026-08-24T00:00:00Z"


class StaticGenerationAuditSourceClient:
    def __init__(self, refs: dict[str, str]) -> None:
        self.refs = refs

    def get_cx_generation(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return _sample_generation_record(self.refs)

    def get_cx_generation_events(
        self,
        cx_generation_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return _sample_progress_payload(self.refs)

    def get_ae_artifact_handoff(
        self,
        artifact_handoff_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return _sample_artifact_handoff(self.refs)

    def get_ae_recovery_request(
        self,
        recovery_request_id: str,
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return {}


def run_ag_generation_quality_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
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
            f"{SMOKE_PROFILE_ENV} must be test for AG PostgreSQL smoke execution.",
            profile=profile,
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        run_service_migrations(SERVICE_ID, database_url=database_url, profile=profile)
        execution = _execute_ag_generation_quality_postgres_smoke(
            database_url=database_url,
            database_env=database_env,
            environ=env,
        )
        raw_values = execution.pop("raw_values", [])
        if "failure_code" in execution:
            return _failure(
                str(execution["failure_code"]),
                str(execution["detail"]),
                profile=profile,
                database_env=database_env,
                checks=execution.get("checks"),
            )
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            **execution,
        }
        if not _redaction_safe(evidence, raw_values):
            return _failure(
                "evidence_redaction_failed",
                "AG generation quality PostgreSQL smoke evidence leaked private data.",
                profile=profile,
                database_env=database_env,
            )
        return evidence
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__, profile=profile)


def _execute_ag_generation_quality_postgres_smoke(
    *,
    database_url: str,
    database_env: str,
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    env = environ if environ is not None else os.environ
    pool_settings = database_pool_settings(SERVICE_ID, workload="api", environ=env)
    engine = build_engine(database_url, pool_settings=pool_settings)
    store = SqlAlchemyOperationalEventStore(build_session_factory(engine))
    refs = _smoke_refs()
    raw_values = [
        refs["raw_prompt"],
        refs["provider_url"],
        refs["api_key"],
    ]
    _delete_smoke_rows(engine, refs=refs)
    try:
        audit_projection = build_generation_audit_projection(
            StaticGenerationAuditSourceClient(refs),
            cx_generation_id=refs["cx_generation_id"],
            artifact_handoff_id=refs["artifact_handoff_id"],
            request_id=refs["request_id"],
            trace_id=refs["trace_id"],
        )
        stored_event = store.append(
            _quality_operational_event(
                refs=refs,
                quality_projection=dict(audit_projection["grounded_response_quality"]),
            )
        )
        listed_events = store.list_events(
            service_id=SERVICE_ID,
            event_type=EVENT_TYPE,
            trace_id=refs["trace_id"],
            limit=10,
        )
        dashboard = build_operations_dashboard_snapshot_projection(
            job_queues={SERVICE_ID: InMemoryJobQueue()},
            event_store=store,
            service_log_stores={SERVICE_ID: InMemoryServiceLogStore()},
            service_id=SERVICE_ID,
            recent_limit=5,
            generation_audit_projections=[audit_projection],
        )
        issue_projection = build_operations_issue_candidate_projection(
            job_queues={SERVICE_ID: InMemoryJobQueue()},
            event_store=store,
            service_log_stores={SERVICE_ID: InMemoryServiceLogStore()},
            service_id=SERVICE_ID,
            recent_limit=5,
            generation_audit_projections=[audit_projection],
        )
        issue_detail = build_generation_quality_issue_detail_projection(
            audit_projection,
            checked_at=CREATED_AT,
            request_trace_id=refs["trace_id"],
        )
        checks = _checks(
            stored_event=stored_event,
            listed_events=listed_events,
            dashboard=dashboard,
            issue_projection=issue_projection,
            issue_detail=issue_detail,
            audit_projection=audit_projection,
            refs=refs,
            raw_values=raw_values,
        )
        if not all(checks.values()):
            return _execution_failure(
                "checks_failed",
                "AG generation quality PostgreSQL smoke checks failed.",
                checks=checks,
                raw_values=raw_values,
            )
        return {
            "cx_generation_id": refs["cx_generation_id"],
            "request_id": refs["request_id"],
            "trace_id": refs["trace_id"],
            "audit_event_id": stored_event["event_id"],
            "projection_versions": {
                "generation_audit": audit_projection.get("projection_schema_version"),
                "grounded_response_quality": audit_projection.get(
                    "grounded_response_quality", {}
                ).get("projection_schema_version"),
                "issue_detail": issue_detail.get("projection_schema_version"),
                "dashboard": dashboard.get("projection_schema_version"),
                "issue_candidates": issue_projection.get("projection_schema_version"),
            },
            "counts": {
                "events": len(listed_events),
                "quality_total": dashboard.get("generation_quality", {})
                .get("summary", {})
                .get("total"),
                "quality_attention": dashboard.get("generation_quality", {})
                .get("summary", {})
                .get("attention_count"),
                "issue_candidates": len(issue_projection.get("issue_candidates", [])),
            },
            "quality_status": {
                "coverage": audit_projection.get("grounded_response_quality", {}).get(
                    "coverage_status"
                ),
                "boundary": audit_projection.get("grounded_response_quality", {}).get(
                    "boundary_status"
                ),
                "issue_codes": audit_projection.get(
                    "grounded_response_quality", {}
                ).get("issue_codes", []),
                "issue_detail_severity": issue_detail.get("severity"),
                "issue_detail_runbook_id": issue_detail.get("runbook", {}).get(
                    "runbook_id"
                ),
            },
            "checks": checks,
            "raw_values": raw_values,
        }
    finally:
        _delete_smoke_rows(engine, refs=refs)


def _smoke_refs() -> dict[str, str]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    cx_generation_id = f"smoke-cx-gen-{request_id}"
    return {
        "request_id": request_id,
        "trace_id": trace_id,
        "cx_generation_id": cx_generation_id,
        "artifact_handoff_id": f"smoke-handoff-{request_id}",
        "event_id": f"smoke-ag-generation-quality-{request_id}",
        "retrieval_package_id": f"smoke-retrieval-{request_id}",
        "retrieval_package_hash": "d" * 64,
        "structured_draft_id": f"smoke-draft-{request_id}",
        "raw_prompt": f"private prompt {request_id}",
        "provider_url": "http://provider-secret.local/v1/chat/completions",
        "api_key": f"secret-api-key-{request_id}",
    }


def _sample_generation_record(refs: dict[str, str]) -> dict[str, Any]:
    return {
        "cx_generation_id": refs["cx_generation_id"],
        "status": "COMPLETED",
        "trace_id": refs["trace_id"],
        "request_id": refs["request_id"],
        "alias": "general-llm-default",
        "provider_capability": "generation",
        "mo_generation_id": f"smoke-mo-gen-{refs['request_id']}",
        "request_metadata": {
            "compatibility_rule_id": "compat-grounded-answer-v1",
            "provider_prompt_package_hash": "a" * 64,
            "generation_request_hash": "b" * 64,
            "grounding_required": True,
            "retrieval_package_id": refs["retrieval_package_id"],
            "retrieval_package_hash": refs["retrieval_package_hash"],
            "selected_evidence_count": 2,
            "structured_draft_id": refs["structured_draft_id"],
            "draft_validation_status": "VALIDATED",
            "raw_prompt": refs["raw_prompt"],
        },
        "response_metadata": {
            "finish_reason": "STOP",
            "output_hash": "c" * 64,
            "output_preview": "Safe preview.",
        },
        "mo_runtime_metadata": {
            "route_id": "route-general-llm-default",
            "provider_request_id": f"provider-{refs['request_id']}",
            "provider_url": refs["provider_url"],
            "api_key": refs["api_key"],
            "total_ms": 12,
        },
        "usage": {"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
    }


def _sample_progress_payload(refs: dict[str, str]) -> dict[str, Any]:
    return {
        "events": [
            {
                "event_id": f"smoke-progress-{refs['request_id']}",
                "event_schema_version": "generation_progress_event.v1",
                "event_type": "generation.prompt.packaged",
                "event_source_service": "nex-cx",
                "trace_id": refs["trace_id"],
                "request_id": refs["request_id"],
                "occurred_at": CREATED_AT,
                "sequence_no": 1,
                "job_status": "RUNNING",
                "current_stage": "PROMPT_ASSEMBLING",
                "progress_mode": "INDETERMINATE",
                "message_key": "generation.progress.prompt_packaged",
                "safe_message": "Prompt package assembled.",
                "retryable": False,
                "details": {
                    "generation_request_hash": "b" * 64,
                    "raw_prompt": refs["raw_prompt"],
                    "provider_url": refs["provider_url"],
                    "api_key": refs["api_key"],
                    "safe": True,
                },
            }
        ]
    }


def _sample_artifact_handoff(refs: dict[str, str]) -> dict[str, Any]:
    return {
        "handoff_schema_version": "ae_artifact_handoff.v1",
        "artifact_handoff_id": refs["artifact_handoff_id"],
        "handoff_status": "READY_FOR_RENDERING",
        "artifact_intent": "create_artifact",
        "target_formats": ["MD", "HTML_PREVIEW"],
        "artifact_title": "Smoke generated report",
        "structured_draft_id": refs["structured_draft_id"],
        "structured_draft_content_hash": "c" * 64,
        "actor_claims_ref": {
            "actor_type": "service",
            "actor_id": SERVICE_ID,
            "tenant_id": "smoke",
        },
        "quality_summary": {
            "citation_status": "VALIDATED",
            "citation_count": 2,
            "validation_error_count": 0,
            "warning_count": 0,
            "grounding_required": True,
            "retrieval_package_id": refs["retrieval_package_id"],
            "retrieval_package_hash": refs["retrieval_package_hash"],
            "evidence_ref_count": 2,
        },
    }


def _quality_operational_event(
    *,
    refs: dict[str, str],
    quality_projection: dict[str, Any],
) -> dict[str, Any]:
    return build_operational_event(
        event_id=refs["event_id"],
        service_id=SERVICE_ID,
        event_type=EVENT_TYPE,
        severity="WARNING",
        message="AG generation quality smoke projection requires attention.",
        trace_id=refs["trace_id"],
        request_id=refs["request_id"],
        subject_ref={"type": "cx.generation", "id": refs["cx_generation_id"]},
        details={
            "cx_generation_id": refs["cx_generation_id"],
            "coverage_status": quality_projection.get("coverage_status"),
            "boundary_status": quality_projection.get("boundary_status"),
            "issue_codes": quality_projection.get("issue_codes", []),
            "projection_issue_count": quality_projection.get("projection_issue_count"),
            "raw_content_included": False,
        },
        created_at=CREATED_AT,
    )


def _delete_smoke_rows(engine: object, *, refs: dict[str, str]) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("""
                DELETE FROM service_operational_events
                WHERE event_id = :event_id
                   OR trace_id = :trace_id
                   OR request_id = :request_id
                """),
            refs,
        )


def _checks(
    *,
    stored_event: dict[str, Any],
    listed_events: list[dict[str, Any]],
    dashboard: dict[str, Any],
    issue_projection: dict[str, Any],
    issue_detail: dict[str, Any],
    audit_projection: dict[str, Any],
    refs: dict[str, str],
    raw_values: list[str],
) -> dict[str, bool]:
    quality = audit_projection.get("grounded_response_quality", {})
    dashboard_quality = dashboard.get("generation_quality", {})
    quality_summary = dashboard_quality.get("summary", {})
    attention = dashboard_quality.get("attention", [])
    quality_candidates = [
        candidate
        for candidate in issue_projection.get("issue_candidates", [])
        if candidate.get("rule_id") == "generation_quality_attention_required.v1"
    ]
    serialized_evidence = json.dumps(
        {
            "stored_event": stored_event,
            "listed_events": listed_events,
            "dashboard_quality": dashboard_quality,
            "quality_candidates": quality_candidates,
            "issue_detail": issue_detail,
            "audit_projection": audit_projection,
        },
        ensure_ascii=False,
    )
    return {
        "postgres_event_roundtrip": (
            stored_event.get("event_id") == refs["event_id"]
            and [event.get("event_id") for event in listed_events] == [refs["event_id"]]
        ),
        "event_details_safe": (
            stored_event.get("details", {}).get("coverage_status") == "WARN"
            and stored_event.get("details", {}).get("raw_content_included") is False
        ),
        "quality_projection_warns_on_missing_cx_metadata": (
            quality.get("coverage_status") == "WARN"
            and quality.get("boundary_status") == "UNKNOWN"
            and "MISSING_CX_GROUNDED_RESPONSE_QUALITY_FIELDS"
            in quality.get("issue_codes", [])
        ),
        "dashboard_surfaces_generation_quality": (
            dashboard_quality.get("projection_schema_version")
            == "ag_generation_quality_dashboard_section.v1"
            and quality_summary.get("total") == 1
            and quality_summary.get("attention_count") == 1
            and [item.get("cx_generation_id") for item in attention]
            == [refs["cx_generation_id"]]
        ),
        "issue_candidate_flags_quality_attention": (
            len(quality_candidates) == 1
            and quality_candidates[0].get("severity") == "WARNING"
            and quality_candidates[0].get("signal", {}).get("status") == "WARN"
            and quality_candidates[0].get("signal", {}).get("cx_generation_ids")
            == [refs["cx_generation_id"]]
        ),
        "issue_detail_contract_valid": _issue_detail_contract_valid(issue_detail),
        "issue_detail_runbook_surfaces_metadata_gap": (
            issue_detail.get("projection_schema_version")
            == "ag_generation_quality_issue_detail_projection.v1"
            and issue_detail.get("severity") == "WARNING"
            and issue_detail.get("attention_required") is True
            and issue_detail.get("runbook", {}).get("runbook_id")
            == "ag.generation_quality.metadata_gap_triage.v1"
            and issue_detail.get("debug_paths", {}).get(
                "generation_audit_detail_path"
            )
            == f"/admin/v1/generation-audit/generations/{refs['cx_generation_id']}"
        ),
        "raw_values_absent_from_ag_evidence": not any(
            value and value in serialized_evidence for value in raw_values
        ),
    }


def _issue_detail_contract_valid(issue_detail: dict[str, Any]) -> bool:
    try:
        Draft202012Validator(_issue_detail_schema()).validate(issue_detail)
    except (ValidationError, OSError, json.JSONDecodeError):
        return False
    return True


def _issue_detail_schema() -> dict[str, Any]:
    return json.loads(
        (
            ROOT
            / "contracts"
            / "schemas"
            / "generation"
            / "ag_generation_quality_issue_detail_projection.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def _execution_failure(
    failure_code: str,
    detail: str,
    *,
    checks: dict[str, bool],
    raw_values: list[str],
) -> dict[str, object]:
    return {
        "failure_code": failure_code,
        "detail": detail,
        "checks": checks,
        "raw_values": raw_values,
    }


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    database_env: str | None = None,
    checks: object | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }
    if database_env is not None:
        payload["database_env"] = database_env
    if checks is not None:
        payload["checks"] = checks
    return payload


def _redaction_safe(evidence: dict[str, object], raw_values: list[str]) -> bool:
    serialized = json.dumps(evidence, ensure_ascii=False)
    return not any(value and value in serialized for value in raw_values)


def summary_line(evidence: dict[str, object]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ag_generation_quality_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        counts = dict(evidence.get("counts", {}))
        quality_status = dict(evidence.get("quality_status", {}))
        return (
            "ag_generation_quality_postgres_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']} "
            f"quality={quality_status.get('coverage')} "
            f"attention={counts.get('quality_attention')} events={counts.get('events')}"
        )
    return (
        "ag_generation_quality_postgres_smoke=fail "
        f"service={evidence.get('service_id', SERVICE_ID)} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the optional AG generation quality PostgreSQL smoke."
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ag_generation_quality_postgres_smoke()
    output = (
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False)
    )
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
