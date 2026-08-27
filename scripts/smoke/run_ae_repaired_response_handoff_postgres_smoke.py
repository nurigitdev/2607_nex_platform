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
AE_PATH = ROOT / "services" / "nex-ae-api"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AE_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))

from nex_ae_api.repaired_responses import (  # noqa: E402
    CX_GENERATION_EXECUTION_RECORD_SCHEMA_VERSION,
    CX_REMEDIATION_EXECUTION_DETAIL_SCHEMA_VERSION,
    CX_REPAIRED_GENERATION_LINEAGE_SCHEMA_VERSION,
    JSON_STORAGE_FIELDS,
    RepairedResponseHandoffError,
    SqlAlchemyRepairedResponseHandoffStore,
    build_repaired_response_handoff_record,
)
from nex_runtime import (  # noqa: E402
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


SCHEMA_VERSION = "ae_repaired_response_handoff_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_REPAIRED_RESPONSE_HANDOFF_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_REPAIRED_RESPONSE_HANDOFF_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = "nex-ae-api"
DEFAULT_PROFILE = "test"
MIGRATION_VERSION = "0383_ae_repaired_response_handoff_persistence"
EXPECTED_JSONB_TYPES = {field_name: "jsonb" for field_name in JSON_STORAGE_FIELDS}
EXPECTED_INDEXES = {
    "ux_ae_repaired_response_handoffs_request",
    "idx_ae_repaired_response_handoffs_owner_time",
    "idx_ae_repaired_response_handoffs_interaction_time",
    "idx_ae_repaired_response_handoffs_parent_generation",
    "idx_ae_repaired_response_handoffs_repair_generation",
    "idx_ae_repaired_response_handoffs_remediation_action",
}


def run_ae_repaired_response_handoff_postgres_smoke(
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
        database_url = service_database_url(
            SERVICE_ID,
            profile=profile,
            environ=env,
        )
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_ae_repaired_handoff_smoke(
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


def _execute_ae_repaired_handoff_smoke(
    *,
    database_url: str,
    database_env: str,
) -> dict[str, Any]:
    request_id = str(uuid4())
    trace_id = uuid4().hex
    suffix = request_id.replace("-", "")[:12]
    handoff_id: str | None = None
    engine = build_engine(database_url)
    try:
        store = SqlAlchemyRepairedResponseHandoffStore(build_session_factory(engine))
        source_payload = _source_payload(suffix)
        record = build_repaired_response_handoff_record(
            source_payload=source_payload,
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
        handoff_id = record["repaired_response_handoff_id"]
        saved = store.save(record)
        loaded = store.get(handoff_id)
        listed = store.list_for_interaction(record["interaction_id"])
        observations = _db_observations(
            engine,
            repaired_response_handoff_id=handoff_id,
        )
        checks = {
            "store_saved_handoff": saved == record,
            "store_loaded_handoff": loaded == saved,
            "interaction_list_scoped": [
                item["repaired_response_handoff_id"] for item in listed
            ]
            == [handoff_id],
            "table_present": observations.get("table_present") is True,
            "migration_recorded": observations.get("migration_recorded") is True,
            "row_count": observations.get("row_count") == 1,
            "schema_version": observations.get("handoff_schema_version")
            == "ae_repaired_response_handoff.v1",
            "jsonb_columns": observations.get("jsonb_columns") == EXPECTED_JSONB_TYPES,
            "indexes_present": observations.get("indexes_present") == sorted(
                EXPECTED_INDEXES
            ),
            "raw_sensitive_absent": _redaction_safe(
                saved,
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
        if not all(checks.values()):
            raise RuntimeError("AE repaired response handoff PostgreSQL checks failed")
        deleted_rows = store.delete(handoff_id)
        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "repaired_response_handoff_id": handoff_id,
            "handoff_request_id": record["handoff_request_id"],
            "interaction_id": record["interaction_id"],
            "db_observations": observations,
            "checks": checks,
            "cleanup": {"deleted_rows": deleted_rows},
        }
    except (RepairedResponseHandoffError, SQLAlchemyError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        if handoff_id is not None:
            _cleanup_handoff(engine, handoff_id)
        engine.dispose()


def _source_payload(suffix: str) -> dict[str, Any]:
    return {
        "tenant_id": f"tenant-ae-handoff-smoke-{suffix}",
        "workspace_id": f"workspace-ae-handoff-smoke-{suffix}",
        "owner_user_id": f"owner-ae-handoff-smoke-{suffix}",
        "chat_document_id": f"chat-doc-ae-handoff-smoke-{suffix}",
        "interaction_id": f"interaction-ae-handoff-smoke-{suffix}",
        "original_cx_generation_id": f"cx-gen-parent-ae-handoff-smoke-{suffix}",
        "remediation_action_id": f"remediation-action-ae-handoff-smoke-{suffix}",
        "handoff_request_id": f"handoff-request-ae-handoff-smoke-{suffix}",
        "actor_claims_ref": {
            "actor_type": "user",
            "actor_id": f"owner-ae-handoff-smoke-{suffix}",
            "tenant_id": f"tenant-ae-handoff-smoke-{suffix}",
        },
    }


def _cx_remediation_detail(
    *,
    suffix: str,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    parent_id = f"cx-gen-parent-ae-handoff-smoke-{suffix}"
    repair_id = f"cx-gen-repair-ae-handoff-smoke-{suffix}"
    action_id = f"remediation-action-ae-handoff-smoke-{suffix}"
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
        "cx_generation_id": f"cx-gen-repair-ae-handoff-smoke-{suffix}",
        "status": "COMPLETED",
        "trace_id": trace_id,
        "request_id": request_id,
        "alias": "general-llm-default",
        "provider_capability": "generation",
        "mo_generation_id": f"mo-gen-repair-ae-handoff-smoke-{suffix}",
        "request_metadata": {
            "provider_prompt_package_hash": "a" * 64,
            "generation_request_hash": "b" * 64,
            "grounding_required": True,
            "retrieval_package_id": f"retrieval-package-ae-handoff-smoke-{suffix}",
            "retrieval_package_hash": "c" * 64,
            "selected_evidence_count": 2,
            "structured_draft_id": f"draft-ae-handoff-smoke-{suffix}",
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


def _db_observations(
    engine: Any,
    *,
    repaired_response_handoff_id: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        table_name = connection.execute(
            text("SELECT to_regclass('public.ae_repaired_response_handoffs')")
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
                        min(handoff_schema_version) AS handoff_schema_version,
                        pg_typeof(actor_claims_ref)::text AS actor_claims_ref_type,
                        pg_typeof(source)::text AS source_type,
                        pg_typeof(repaired_response)::text AS repaired_response_type,
                        pg_typeof(lineage)::text AS lineage_type,
                        pg_typeof(user_surface)::text AS user_surface_type,
                        pg_typeof(links)::text AS links_type,
                        pg_typeof(redaction_summary)::text AS redaction_summary_type
                    FROM ae_repaired_response_handoffs
                    WHERE repaired_response_handoff_id = :handoff_id
                    GROUP BY
                        pg_typeof(actor_claims_ref)::text,
                        pg_typeof(source)::text,
                        pg_typeof(repaired_response)::text,
                        pg_typeof(lineage)::text,
                        pg_typeof(user_surface)::text,
                        pg_typeof(links)::text,
                        pg_typeof(redaction_summary)::text
                    """
                ),
                {"handoff_id": repaired_response_handoff_id},
            )
            .mappings()
            .first()
        )
        indexes = (
            connection.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = 'ae_repaired_response_handoffs'
                    ORDER BY indexname
                    """
                )
            )
            .scalars()
            .all()
        )
    return {
        "table_present": table_name == "ae_repaired_response_handoffs",
        "migration_recorded": bool(migration_recorded),
        "row_count": int(row["row_count"]) if row else 0,
        "handoff_schema_version": row["handoff_schema_version"] if row else None,
        "jsonb_columns": {
            "actor_claims_ref": row["actor_claims_ref_type"] if row else None,
            "source": row["source_type"] if row else None,
            "repaired_response": row["repaired_response_type"] if row else None,
            "lineage": row["lineage_type"] if row else None,
            "user_surface": row["user_surface_type"] if row else None,
            "links": row["links_type"] if row else None,
            "redaction_summary": row["redaction_summary_type"] if row else None,
        },
        "indexes_present": sorted(set(indexes).intersection(EXPECTED_INDEXES)),
    }


def _cleanup_handoff(engine: Any, repaired_response_handoff_id: str) -> None:
    try:
        with engine.begin() as connection:
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
        raise ValueError("AE repaired response handoff smoke contains raw database URL.")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"ae_repaired_response_handoff_postgres_smoke=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "ae_repaired_response_handoff_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"handoff_id={evidence['repaired_response_handoff_id']} "
            f"row_count={evidence['db_observations']['row_count']} "
            f"deleted_rows={evidence['cleanup']['deleted_rows']}"
        )
    return (
        "ae_repaired_response_handoff_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AE repaired response handoff PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_repaired_response_handoff_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
