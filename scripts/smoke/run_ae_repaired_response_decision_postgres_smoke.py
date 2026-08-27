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
AE_PATH = ROOT / "services" / "nex-ae-api"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AE_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))

from nex_ae_api.repaired_response_decisions import (  # noqa: E402
    AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION,
    DECISION_ACTION_ACCEPT_REPAIR,
    JSON_STORAGE_FIELDS,
    RepairedResponseDecisionError,
    SqlAlchemyRepairedResponseDecisionStore,
    register_repaired_response_decision_routes,
)
from nex_ae_api.repaired_responses import (  # noqa: E402
    CX_GENERATION_EXECUTION_RECORD_SCHEMA_VERSION,
    CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION,
    CX_REPAIRED_GENERATION_LINEAGE_SCHEMA_VERSION,
    RepairedResponseHandoffError,
    SqlAlchemyRepairedResponseHandoffStore,
    build_repaired_response_handoff_record,
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


SCHEMA_VERSION = "ae_repaired_response_decision_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_REPAIRED_RESPONSE_DECISION_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_REPAIRED_RESPONSE_DECISION_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = "nex-ae-api"
DEFAULT_PROFILE = "test"
MIGRATION_VERSION = "0387_ae_repaired_response_decision_persistence"
EXPECTED_JSONB_TYPES = {field_name: "jsonb" for field_name in JSON_STORAGE_FIELDS}
EXPECTED_INDEXES = {
    "ux_ae_repaired_response_decisions_request",
    "idx_ae_repaired_response_decisions_handoff_time",
    "idx_ae_repaired_response_decisions_interaction_time",
    "idx_ae_repaired_response_decisions_owner_time",
    "idx_ae_repaired_response_decisions_selected_generation",
    "idx_ae_repaired_response_decisions_remediation_action",
}


def run_ae_repaired_response_decision_postgres_smoke(
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
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_ae_repaired_decision_smoke(
            database_url=database_url,
            database_env=database_env,
        )
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__, profile=profile)

    evidence = {
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
        **execution,
    }
    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _execute_ae_repaired_decision_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    handoff_id: str | None = None
    decision_id: str | None = None
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        handoff_store = SqlAlchemyRepairedResponseHandoffStore(session_factory)
        decision_store = SqlAlchemyRepairedResponseDecisionStore(session_factory)
        handoff = build_repaired_response_handoff_record(
            source_payload=_source_payload(suffix),
            cx_remediation_detail=_cx_remediation_detail(
                suffix=suffix,
                request_id=request_id,
                trace_id=trace_id,
            ),
            repaired_generation_record=_repaired_generation_record(
                suffix=suffix,
                request_id=request_id,
                trace_id=trace_id,
            ),
            handoff_request_id=None,
            request_id=request_id,
            trace_id=trace_id,
        )
        handoff_id = handoff["repaired_response_handoff_id"]
        saved_handoff = handoff_store.save(handoff)
        app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        register_repaired_response_decision_routes(
            app,
            handoff_store=handoff_store,
            decision_store=decision_store,
        )
        client = TestClient(app)
        route = (
            f"/api/v1/chat/interactions/{handoff['interaction_id']}/"
            f"repaired-response-handoffs/{handoff_id}/decisions"
        )
        create_response = client.post(
            route,
            json=_decision_payload(suffix),
            headers=_auth_headers(request_id=request_id, trace_id=trace_id),
        )
        if create_response.status_code != 202:
            raise RuntimeError("AE repaired response decision route create failed")
        created = create_response.json()
        decision_id = created["repaired_response_decision_id"]
        list_response = client.get(
            route,
            headers=_auth_headers(request_id=request_id, trace_id=trace_id),
        )
        detail_response = client.get(
            f"{route}/{decision_id}",
            headers=_auth_headers(request_id=request_id, trace_id=trace_id),
        )
        loaded = decision_store.get(decision_id)
        listed = decision_store.list_for_handoff(handoff_id)
        observations = _db_observations(
            engine,
            repaired_response_decision_id=decision_id,
            repaired_response_handoff_id=handoff_id,
        )
        checks = {
            "route_created_decision": create_response.status_code == 202,
            "route_listed_decision": list_response.status_code == 200
            and [
                item["repaired_response_decision_id"]
                for item in list_response.json()["items"]
            ]
            == [decision_id],
            "route_loaded_decision": detail_response.status_code == 200
            and _decision_records_match(detail_response.json(), created),
            "store_loaded_decision": loaded is not None
            and _decision_records_match(loaded, created),
            "store_list_scoped": [
                item["repaired_response_decision_id"] for item in listed
            ]
            == [decision_id],
            "handoff_saved": saved_handoff == handoff,
            "table_present": observations.get("table_present") is True,
            "migration_recorded": observations.get("migration_recorded") is True,
            "row_count": observations.get("row_count") == 1,
            "handoff_row_count": observations.get("handoff_row_count") == 1,
            "schema_version": observations.get("decision_schema_version")
            == AE_REPAIRED_RESPONSE_DECISION_SCHEMA_VERSION,
            "decision_action": observations.get("decision_action")
            == DECISION_ACTION_ACCEPT_REPAIR,
            "selected_generation": observations.get("selected_cx_generation_id")
            == handoff["source"]["repair_cx_generation_id"],
            "jsonb_columns": observations.get("jsonb_columns") == EXPECTED_JSONB_TYPES,
            "indexes_present": observations.get("indexes_present") == sorted(
                EXPECTED_INDEXES
            ),
            "raw_sensitive_absent": _redaction_safe(
                created,
                loaded,
                observations,
                forbidden_fragments=[
                    database_url,
                    database_env,
                    "nuri1004",
                    "raw answer body",
                    "hidden prompt",
                    "/data/nex-platform",
                ],
            ),
        }
        failed_checks = [key for key, passed in checks.items() if not passed]
        if failed_checks:
            raise RuntimeError(
                "AE repaired response decision PostgreSQL checks failed: "
                f"{', '.join(failed_checks)}"
            )
        deleted_decisions = decision_store.delete(decision_id)
        deleted_handoffs = handoff_store.delete(handoff_id)
        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "repaired_response_handoff_id": handoff_id,
            "repaired_response_decision_id": decision_id,
            "decision_request_id": created["decision_request_id"],
            "interaction_id": handoff["interaction_id"],
            "db_observations": observations,
            "checks": checks,
            "cleanup": {
                "deleted_decisions": deleted_decisions,
                "deleted_handoffs": deleted_handoffs,
            },
        }
    except (
        RepairedResponseDecisionError,
        RepairedResponseHandoffError,
        SQLAlchemyError,
        ValueError,
    ) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        _cleanup_smoke_rows(
            engine,
            repaired_response_decision_id=decision_id,
            repaired_response_handoff_id=handoff_id,
        )
        engine.dispose()


def _source_payload(suffix: str) -> dict[str, Any]:
    return {
        "tenant_id": f"tenant-ae-decision-smoke-{suffix}",
        "workspace_id": f"workspace-ae-decision-smoke-{suffix}",
        "owner_user_id": f"owner-ae-decision-smoke-{suffix}",
        "chat_document_id": f"chat-doc-ae-decision-smoke-{suffix}",
        "interaction_id": f"interaction-ae-decision-smoke-{suffix}",
        "original_cx_generation_id": f"cx-gen-parent-ae-decision-smoke-{suffix}",
        "remediation_action_id": f"remediation-action-ae-decision-smoke-{suffix}",
        "handoff_request_id": f"handoff-request-ae-decision-smoke-{suffix}",
        "actor_claims_ref": {
            "actor_type": "user",
            "actor_id": f"owner-ae-decision-smoke-{suffix}",
            "tenant_id": f"tenant-ae-decision-smoke-{suffix}",
        },
    }


def _cx_remediation_detail(
    *,
    suffix: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    parent_id = f"cx-gen-parent-ae-decision-smoke-{suffix}"
    repair_id = f"cx-gen-repair-ae-decision-smoke-{suffix}"
    action_id = f"remediation-action-ae-decision-smoke-{suffix}"
    lineage = {
        "lineage_schema_version": CX_REPAIRED_GENERATION_LINEAGE_SCHEMA_VERSION,
        "lineage_status": "LINKED",
        "parent_cx_generation_id": parent_id,
        "root_cx_generation_id": parent_id,
        "repair_cx_generation_id": repair_id,
        "remediation_action_id": action_id,
        "action_type": "citation_repair",
        "lineage_type": "repair",
        "execution_status": "SUCCEEDED",
        "attempt_no": 1,
        "result_ref": {
            "source_service": "nex-cx",
            "ref_type": "repair_execution",
            "ref_id": action_id,
            "relation": "result_of",
        },
        "diagnostics": {
            "lineage_consistent": True,
            "repair_generation_linked": True,
            "result_ref_present": True,
            "result_ref_matches_remediation_action": True,
            "parent_generation_mutated": False,
        },
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
        },
    }
    return {
        "detail_schema_version": CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION,
        "projection_status": "READY",
        "checked_at": "2026-08-27T00:00:00Z",
        "parent_cx_generation_id": parent_id,
        "remediation_action_id": action_id,
        "trace_id": trace_id,
        "request_id": request_id,
        "execution_status": "SUCCEEDED",
        "execution": {
            "result_schema_version": "cx_remediation_execution_result.v1",
            "remediation_action_id": action_id,
            "parent_cx_generation_id": parent_id,
            "repair_cx_generation_id": repair_id,
            "execution_status": "SUCCEEDED",
        },
        "repaired_generation_lineage": lineage,
        "attention_required": False,
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
        },
    }


def _repaired_generation_record(
    *,
    suffix: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    return {
        "record_schema_version": CX_GENERATION_EXECUTION_RECORD_SCHEMA_VERSION,
        "cx_generation_id": f"cx-gen-repair-ae-decision-smoke-{suffix}",
        "status": "COMPLETED",
        "trace_id": trace_id,
        "request_id": request_id,
        "alias": "general-llm-default",
        "provider_capability": "generation",
        "mo_generation_id": f"mo-gen-repair-ae-decision-smoke-{suffix}",
        "request_metadata": {
            "provider_prompt_package_hash": "a" * 64,
            "generation_request_hash": "b" * 64,
            "grounding_required": True,
            "retrieval_package_id": f"retrieval-package-ae-decision-smoke-{suffix}",
            "retrieval_package_hash": "c" * 64,
            "selected_evidence_count": 2,
            "structured_draft_id": f"draft-ae-decision-smoke-{suffix}",
            "draft_validation_status": "VALIDATED",
            "grounded_response_quality_status": "PASS",
            "grounded_response_quality_issue_count": 0,
        },
        "response_metadata": {
            "finish_reason": "STOP",
            "output_hash": "d" * 64,
            "output_preview": "Repaired answer preview with safe citation support.",
        },
        "usage": {
            "input_tokens": 12,
            "output_tokens": 16,
            "total_tokens": 28,
        },
        "created_at": "2026-08-27T00:00:00Z",
        "updated_at": "2026-08-27T00:00:00Z",
    }


def _decision_payload(suffix: str) -> dict[str, Any]:
    return {
        "decision_action": DECISION_ACTION_ACCEPT_REPAIR,
        "decision_request_id": f"decision-request-ae-decision-smoke-{suffix}",
        "decision_reason_codes": ["citation_fixed", "prefer_repaired"],
        "decision_comment": "The repaired response is acceptable for this smoke.",
        "submitted_via": "chat_review",
    }


def _auth_headers(*, request_id: str, trace_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ag", audience=SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _decision_records_match(candidate: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    compared_fields = (
        "decision_schema_version",
        "repaired_response_decision_id",
        "decision_request_id",
        "decision_status",
        "decision_action",
        "repaired_response_handoff_id",
        "handoff_request_id",
        "tenant_id",
        "workspace_id",
        "owner_user_id",
        "chat_document_id",
        "interaction_id",
        "parent_cx_generation_id",
        "repair_cx_generation_id",
        "selected_cx_generation_id",
        "rejected_cx_generation_id",
        "remediation_action_id",
        "decision_comment_hash",
    )
    return all(candidate.get(field_name) == expected.get(field_name) for field_name in compared_fields)


def _db_observations(
    engine: Any,
    *,
    repaired_response_decision_id: str,
    repaired_response_handoff_id: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        table_name = connection.execute(
            text("SELECT to_regclass('public.ae_repaired_response_decisions')")
        ).scalar()
        migration_recorded = connection.execute(
            text(
                """
                SELECT EXISTS(
                    SELECT 1 FROM schema_migrations WHERE version = :version
                )
                """
            ),
            {"version": MIGRATION_VERSION},
        ).scalar()
        row = (
            connection.execute(
                text(
                    """
                    SELECT
                        count(*) AS row_count,
                        min(decision_schema_version) AS decision_schema_version,
                        min(decision_action) AS decision_action,
                        min(selected_cx_generation_id) AS selected_cx_generation_id,
                        pg_typeof(actor_claims_ref)::text AS actor_claims_ref_type,
                        pg_typeof(decision_reason_codes)::text AS reason_codes_type,
                        pg_typeof(metadata)::text AS metadata_type
                    FROM ae_repaired_response_decisions
                    WHERE repaired_response_decision_id = :decision_id
                    GROUP BY
                        pg_typeof(actor_claims_ref)::text,
                        pg_typeof(decision_reason_codes)::text,
                        pg_typeof(metadata)::text
                    """
                ),
                {"decision_id": repaired_response_decision_id},
            )
            .mappings()
            .first()
        )
        handoff_row_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM ae_repaired_response_handoffs
                WHERE repaired_response_handoff_id = :handoff_id
                """
            ),
            {"handoff_id": repaired_response_handoff_id},
        ).scalar()
        indexes = (
            connection.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = 'ae_repaired_response_decisions'
                    ORDER BY indexname
                    """
                )
            )
            .scalars()
            .all()
        )
    return {
        "table_present": table_name == "ae_repaired_response_decisions",
        "migration_recorded": bool(migration_recorded),
        "row_count": int(row["row_count"]) if row else 0,
        "handoff_row_count": int(handoff_row_count or 0),
        "decision_schema_version": row["decision_schema_version"] if row else None,
        "decision_action": row["decision_action"] if row else None,
        "selected_cx_generation_id": (
            row["selected_cx_generation_id"] if row else None
        ),
        "jsonb_columns": {
            "actor_claims_ref": row["actor_claims_ref_type"] if row else None,
            "decision_reason_codes": row["reason_codes_type"] if row else None,
            "metadata": row["metadata_type"] if row else None,
        },
        "indexes_present": sorted(set(indexes).intersection(EXPECTED_INDEXES)),
    }


def _cleanup_smoke_rows(
    engine: Any,
    *,
    repaired_response_decision_id: str | None,
    repaired_response_handoff_id: str | None,
) -> None:
    try:
        with engine.begin() as connection:
            if repaired_response_decision_id:
                connection.execute(
                    text(
                        """
                        DELETE FROM ae_repaired_response_decisions
                        WHERE repaired_response_decision_id = :decision_id
                        """
                    ),
                    {"decision_id": repaired_response_decision_id},
                )
            if repaired_response_handoff_id:
                connection.execute(
                    text(
                        """
                        DELETE FROM ae_repaired_response_handoffs
                        WHERE repaired_response_handoff_id = :handoff_id
                        """
                    ),
                    {"handoff_id": repaired_response_handoff_id},
                )
    except SQLAlchemyError:
        return


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


def _redaction_safe(
    *payloads: Any,
    forbidden_fragments: list[str],
) -> bool:
    serialized = json.dumps(payloads, ensure_ascii=False, sort_keys=True, default=str)
    return all(fragment not in serialized for fragment in forbidden_fragments)


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    database_url = environ.get(service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE))
    if database_url and database_url in serialized_evidence:
        raise ValueError("AE repaired response decision smoke contains raw database URL.")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ae_repaired_response_decision_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "ae_repaired_response_decision_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"handoff_id={evidence['repaired_response_handoff_id']} "
            f"decision_id={evidence['repaired_response_decision_id']} "
            f"row_count={evidence['db_observations']['row_count']} "
            f"deleted_decisions={evidence['cleanup']['deleted_decisions']} "
            f"deleted_handoffs={evidence['cleanup']['deleted_handoffs']}"
        )
    return (
        "ae_repaired_response_decision_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AE repaired response decision PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_repaired_response_decision_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
