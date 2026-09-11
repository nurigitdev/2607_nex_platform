#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
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
AG_PATH = ROOT / "services" / "nex-ag"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))

from nex_ag.operator_review_cases import (  # noqa: E402
    OperatorReviewCaseStore,
    SqlAlchemyOperatorReviewCaseStore,
    register_operator_review_case_routes,
)
from nex_ag.operator_reviews import (  # noqa: E402
    OperatorReviewNoteError,
    SqlAlchemyOperatorEvidenceExportStore,
    SqlAlchemyOperatorReviewNoteStore,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    issue_mock_user_token,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_operator_review_case_evidence_admission_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_OPERATOR_REVIEW_CASE_EVIDENCE_ADMISSION_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
RAW_NOTE = "AG case evidence/admission smoke raw note must not appear."
RAW_EXPORT_BODY = "AG case evidence/admission smoke raw export must not appear."


def run_ag_operator_review_case_evidence_admission_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    database_url = env.get(DATABASE_ENV)
    if not database_url:
        return _failure("database_url_missing", f"{DATABASE_ENV} is required.")

    try:
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=PROFILE,
        )
    except MigrationError as exc:
        return _failure("migration_failed", str(exc))

    suffix = uuid4().hex[:12]
    request_id = f"ag-op-case-evidence-admission-smoke-{suffix}"
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    target_id = f"ag-op-case-evidence-admission-smoke-target-{suffix}"
    case_id: str | None = None
    operator_note_id = f"ag-op-case-evidence-admission-note-{suffix}"
    export_id = f"ag-op-case-evidence-admission-export-{suffix}"
    idempotency_key = f"ag-op-case-evidence-admission-idem-{suffix}"
    engine: Any | None = None
    try:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        case_store = SqlAlchemyOperatorReviewCaseStore(session_factory)
        note_store = SqlAlchemyOperatorReviewNoteStore(session_factory)
        export_store = SqlAlchemyOperatorEvidenceExportStore(session_factory)
        app = build_service_app(SERVICE_SPECS[SERVICE_ID])
        register_operator_review_case_routes(
            app,
            store=case_store,
            note_store=note_store,
            export_store=export_store,
        )
        client = TestClient(app)
        create_response = client.post(
            "/admin/v1/operator-review/cases",
            headers=_admin_headers(
                request_id=request_id,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
            ),
            json=_case_payload(suffix=suffix, target_id=target_id),
        )
        create_body = create_response.json()
        case_id = (
            create_body.get("case", {}).get("case_id")
            if isinstance(create_body, dict)
            else None
        )
        note_store.save(
            _note_record(
                operator_note_id=operator_note_id,
                suffix=suffix,
                request_id=request_id,
                trace_id=trace_id,
                target_id=target_id,
            )
        )
        export_store.save(
            _export_record(
                export_id=export_id,
                suffix=suffix,
                request_id=request_id,
                trace_id=trace_id,
                target_id=target_id,
            )
        )
        detail_response = client.get(
            f"/admin/v1/operator-review/cases/{case_id}/workbench-detail",
            headers=_admin_headers(request_id=request_id, trace_id=trace_id),
        )
        evidence_response = client.get(
            f"/admin/v1/operator-review/cases/{case_id}/evidence-links?limit=5",
            headers=_admin_headers(request_id=request_id, trace_id=trace_id),
        )
        admission_response = client.get(
            f"/admin/v1/operator-review/cases/{case_id}/action-admission"
            "?action_type=RESOLVE",
            headers=_admin_headers(request_id=request_id, trace_id=trace_id),
        )
        observations = _db_observations(
            engine,
            case_id=case_id,
            target_id=target_id,
            operator_note_id=operator_note_id,
            export_id=export_id,
        )
        detail_body = detail_response.json()
        evidence_body = evidence_response.json()
        admission_body = admission_response.json()
        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "case_create_status": create_response.status_code == 201,
            "detail_status": detail_response.status_code == 200,
            "detail_evidence_ready": detail_body.get("evidence_links", {})
            .get("summary", {})
            .get("evidence_source_status")
            == "READY",
            "detail_evidence_count": detail_body.get("evidence_links", {})
            .get("summary", {})
            .get("total_link_count")
            == 2,
            "detail_action_admission_linked": detail_body.get("action_admission", {})
            .get("links", {})
            .get("case_action_admission_path")
            == f"/admin/v1/operator-review/cases/{case_id}/action-admission",
            "detail_action_admission_not_inline": detail_body.get(
                "action_admission", {}
            ).get("inline_items_included")
            is False,
            "evidence_status": evidence_response.status_code == 200,
            "evidence_summary_ready": evidence_body.get("summary", {}).get(
                "evidence_source_status"
            )
            == "READY",
            "evidence_note_count": evidence_body.get("summary", {}).get(
                "operator_note_count"
            )
            == 1,
            "evidence_export_count": evidence_body.get("summary", {}).get(
                "redacted_evidence_export_count"
            )
            == 1,
            "evidence_links_redacted": _redaction_flags_are_false(
                evidence_body.get("redaction", {}),
                (
                    "raw_operator_note_included",
                    "raw_evidence_body_included",
                    "storage_paths_included",
                    "idempotency_keys_included",
                    "provider_payloads_included",
                    "database_urls_included",
                    "tokens_included",
                ),
            ),
            "admission_status": admission_response.status_code == 200,
            "admission_requested_resolve": admission_body.get("summary", {}).get(
                "requested_action_type"
            )
            == "RESOLVE",
            "admission_requested_admitted": admission_body.get("summary", {}).get(
                "requested_action_admitted"
            )
            is True,
            "admission_requires_resolution": admission_body.get(
                "requested_action", {}
            ).get("requires_resolution_comment")
            is True,
            "admission_redacted": _redaction_flags_are_false(
                admission_body.get("redaction", {}),
                (
                    "raw_action_comment_included",
                    "raw_resolution_comment_included",
                    "idempotency_keys_included",
                    "provider_payloads_included",
                    "database_urls_included",
                    "tokens_included",
                ),
            ),
            "tables_present": observations.get("tables_present") == {
                "ag_op_cases": True,
                "ag_op_notes": True,
                "ag_ev_exports": True,
            },
            "case_row_persisted": observations.get("case_count") == 1,
            "note_row_persisted": observations.get("note_count") == 1,
            "export_row_persisted": observations.get("export_count") == 1,
            "jsonb_columns": observations.get("jsonb_columns")
            == {
                "case_metadata": "jsonb",
                "note_metadata": "jsonb",
                "export_manifest": "jsonb",
                "export_metadata": "jsonb",
            },
            "raw_payloads_not_persisted": observations.get("raw_payload_leak_count")
            == 0,
        }
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS" if all(checks.values()) else "FAIL",
            "failure_code": None if all(checks.values()) else "checks_failed",
            "service": SERVICE_ID,
            "profile": PROFILE,
            "database_env": DATABASE_ENV,
            "redacted_database_url": redact_database_url(database_url),
            "migration": {
                "planned": list(migration.planned),
                "applied": list(migration.applied),
                "skipped": list(migration.skipped),
            },
            "request_id": request_id,
            "trace_id": trace_id,
            "case_id": case_id,
            "target_id": target_id,
            "observations": observations,
            "checks": checks,
            "cleanup": _cleanup_smoke_rows(
                engine,
                case_id=case_id,
                target_id=target_id,
                operator_note_id=operator_note_id,
                export_id=export_id,
            ),
        }
    except (OperatorReviewNoteError, SQLAlchemyError, ValueError) as exc:
        evidence = _failure("smoke_execution_failed", str(exc))
    finally:
        if engine is not None:
            _cleanup_smoke_rows(
                engine,
                case_id=case_id,
                target_id=target_id,
                operator_note_id=operator_note_id,
                export_id=export_id,
            )
            engine.dispose()

    assert_smoke_evidence_redacted(
        json.dumps(evidence, default=str),
        env,
        raw_values=(RAW_NOTE, RAW_EXPORT_BODY, idempotency_key),
    )
    return evidence


def _case_payload(*, suffix: str, target_id: str) -> dict[str, Any]:
    return {
        "target_ref": {
            "target_service": "nex-ag",
            "target_kind": "operator_review_workbench",
            "target_id": target_id,
        },
        "operator_ref": {
            "operator_type": "user",
            "operator_id": f"smoke-operator-{suffix}",
            "tenant_id": "smoke-tenant",
        },
        "case_status": "OPEN",
        "case_priority": "HIGH",
        "source_ref": {
            "source_type": "operator_review_workbench",
            "source_id": target_id,
            "source_service": "nex-ag",
            "workbench_path": "/admin/v1/operator-review/cases/queue",
        },
        "reason_codes": ["postgres_smoke", "operator_review_case_evidence_admission"],
        "resolution_comment": "Bounded smoke resolution preview.",
        "metadata": {"source": "postgres_smoke", "slice": "0668"},
    }


def _note_record(
    *,
    operator_note_id: str,
    suffix: str,
    request_id: str,
    trace_id: str,
    target_id: str,
) -> dict[str, Any]:
    return {
        "operator_note_schema_version": "ag_operator_review_note.v1",
        "operator_note_id": operator_note_id,
        "target_service": "nex-ag",
        "target_kind": "operator_review_workbench",
        "target_id": target_id,
        "trace_id": trace_id,
        "request_id": request_id,
        "operator_ref": {
            "operator_type": "user",
            "operator_id": f"smoke-operator-{suffix}",
            "tenant_id": "smoke-tenant",
        },
        "note_status": "ACTIVE",
        "note_type": "FOLLOW_UP",
        "severity": "HIGH",
        "operator_note_hash": _sha256_text(RAW_NOTE),
        "operator_note_preview": "Bounded smoke note preview.",
        "reason_codes": ["operator_review_case_evidence_admission"],
        "metadata": {
            "raw_operator_note_stored": False,
            "slice": "0668",
        },
        "created_at": "2026-09-11T00:01:00Z",
        "updated_at": "2026-09-11T00:03:00Z",
    }


def _export_record(
    *,
    export_id: str,
    suffix: str,
    request_id: str,
    trace_id: str,
    target_id: str,
) -> dict[str, Any]:
    return {
        "export_schema_version": "ag_redacted_evidence_export.v1",
        "export_id": export_id,
        "target_service": "nex-ag",
        "target_kind": "operator_review_workbench",
        "target_id": target_id,
        "trace_id": trace_id,
        "request_id": request_id,
        "operator_ref": {
            "operator_type": "user",
            "operator_id": f"smoke-operator-{suffix}",
            "tenant_id": "smoke-tenant",
        },
        "export_status": "READY",
        "export_format": "json",
        "redaction_profile": "ag_redacted_manifest_v1",
        "evidence_manifest": {
            "items": [
                {
                    "evidence_type": "operator_note",
                    "redaction_status": "REDACTED",
                }
            ]
        },
        "evidence_hash": _sha256_text(RAW_EXPORT_BODY),
        "evidence_item_count": 1,
        "metadata": {
            "raw_evidence_body_stored": False,
            "slice": "0668",
        },
        "created_at": "2026-09-11T00:02:00Z",
        "updated_at": "2026-09-11T00:02:30Z",
    }


def _admin_headers(
    *,
    request_id: str,
    trace_id: str,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id="smoke-tenant",
        user_id="smoke-admin",
        audience="nex-ag",
        roles=["admin"],
    )
    headers = {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _db_observations(
    engine: Any,
    *,
    case_id: str | None,
    target_id: str,
    operator_note_id: str,
    export_id: str,
) -> dict[str, Any]:
    with engine.connect() as connection:
        case_table = connection.execute(
            text("SELECT to_regclass('public.ag_op_cases')")
        ).scalar()
        note_table = connection.execute(
            text("SELECT to_regclass('public.ag_op_notes')")
        ).scalar()
        export_table = connection.execute(
            text("SELECT to_regclass('public.ag_ev_exports')")
        ).scalar()
        row = (
            connection.execute(
                text(
                    """
                    SELECT
                        (
                            SELECT count(*)
                            FROM ag_op_cases
                            WHERE case_id = :case_id
                                AND target_id = :target_id
                        ) AS case_count,
                        (
                            SELECT count(*)
                            FROM ag_op_notes
                            WHERE operator_note_id = :operator_note_id
                                AND target_id = :target_id
                        ) AS note_count,
                        (
                            SELECT count(*)
                            FROM ag_ev_exports
                            WHERE export_id = :export_id
                                AND target_id = :target_id
                        ) AS export_count,
                        (
                            SELECT pg_typeof(metadata)::text
                            FROM ag_op_cases
                            WHERE case_id = :case_id
                            LIMIT 1
                        ) AS case_metadata_type,
                        (
                            SELECT pg_typeof(metadata)::text
                            FROM ag_op_notes
                            WHERE operator_note_id = :operator_note_id
                            LIMIT 1
                        ) AS note_metadata_type,
                        (
                            SELECT pg_typeof(evidence_manifest)::text
                            FROM ag_ev_exports
                            WHERE export_id = :export_id
                            LIMIT 1
                        ) AS export_manifest_type,
                        (
                            SELECT pg_typeof(metadata)::text
                            FROM ag_ev_exports
                            WHERE export_id = :export_id
                            LIMIT 1
                        ) AS export_metadata_type,
                        (
                            SELECT count(*)
                            FROM (
                                SELECT metadata::text AS body
                                FROM ag_op_notes
                                WHERE operator_note_id = :operator_note_id
                                UNION ALL
                                SELECT evidence_manifest::text AS body
                                FROM ag_ev_exports
                                WHERE export_id = :export_id
                                UNION ALL
                                SELECT metadata::text AS body
                                FROM ag_ev_exports
                                WHERE export_id = :export_id
                            ) AS redaction_probe
                            WHERE body LIKE '%' || :raw_note || '%'
                                OR body LIKE '%' || :raw_export_body || '%'
                        ) AS raw_payload_leak_count
                    """
                ),
                {
                    "case_id": case_id or "",
                    "target_id": target_id,
                    "operator_note_id": operator_note_id,
                    "export_id": export_id,
                    "raw_note": RAW_NOTE,
                    "raw_export_body": RAW_EXPORT_BODY,
                },
            )
            .mappings()
            .one()
        )
    return {
        "tables_present": {
            "ag_op_cases": _regclass_matches(case_table, "ag_op_cases"),
            "ag_op_notes": _regclass_matches(note_table, "ag_op_notes"),
            "ag_ev_exports": _regclass_matches(export_table, "ag_ev_exports"),
        },
        "case_count": int(row["case_count"]),
        "note_count": int(row["note_count"]),
        "export_count": int(row["export_count"]),
        "jsonb_columns": {
            "case_metadata": row["case_metadata_type"],
            "note_metadata": row["note_metadata_type"],
            "export_manifest": row["export_manifest_type"],
            "export_metadata": row["export_metadata_type"],
        },
        "raw_payload_leak_count": int(row["raw_payload_leak_count"]),
    }


def _cleanup_smoke_rows(
    engine: Any,
    *,
    case_id: str | None,
    target_id: str | None,
    operator_note_id: str | None,
    export_id: str | None,
) -> dict[str, int]:
    if not any((case_id, target_id, operator_note_id, export_id)):
        return {"cases": 0, "notes": 0, "exports": 0}
    deleted_cases = 0
    deleted_notes = 0
    deleted_exports = 0
    try:
        with engine.begin() as connection:
            if operator_note_id or target_id:
                where, params = _cleanup_where(
                    id_column="operator_note_id",
                    id_value=operator_note_id,
                    target_id=target_id,
                )
                result = connection.execute(
                    text(f"DELETE FROM ag_op_notes WHERE {where}"),
                    params,
                )
                deleted_notes = int(result.rowcount or 0)
            if export_id or target_id:
                where, params = _cleanup_where(
                    id_column="export_id",
                    id_value=export_id,
                    target_id=target_id,
                )
                result = connection.execute(
                    text(f"DELETE FROM ag_ev_exports WHERE {where}"),
                    params,
                )
                deleted_exports = int(result.rowcount or 0)
            if case_id or target_id:
                where, params = _cleanup_where(
                    id_column="case_id",
                    id_value=case_id,
                    target_id=target_id,
                )
                result = connection.execute(
                    text(f"DELETE FROM ag_op_cases WHERE {where}"),
                    params,
                )
                deleted_cases = int(result.rowcount or 0)
    except (AttributeError, SQLAlchemyError):
        return {"cases": 0, "notes": 0, "exports": 0}
    return {"cases": deleted_cases, "notes": deleted_notes, "exports": deleted_exports}


def _cleanup_where(
    *,
    id_column: str,
    id_value: str | None,
    target_id: str | None,
) -> tuple[str, dict[str, str]]:
    clauses: list[str] = []
    params: dict[str, str] = {}
    if id_value:
        clauses.append(f"{id_column} = :id_value")
        params["id_value"] = id_value
    if target_id:
        clauses.append("target_id = :target_id")
        params["target_id"] = target_id
    return " OR ".join(clauses), params


def _redaction_flags_are_false(
    redaction: object,
    keys: tuple[str, ...],
) -> bool:
    if not isinstance(redaction, Mapping):
        return False
    return all(redaction.get(key) is False for key in keys)


def _regclass_matches(value: object, table_name: str) -> bool:
    if value is None:
        return False
    return str(value).split(".")[-1] == table_name


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
    *,
    raw_values: tuple[str, ...],
) -> None:
    database_url = environ.get(DATABASE_ENV)
    if database_url and database_url in serialized_evidence:
        raise ValueError("AG case evidence/admission smoke evidence contains raw DB URL.")
    for raw_value in raw_values:
        if raw_value and raw_value in serialized_evidence:
            raise ValueError(
                "AG case evidence/admission smoke evidence contains raw sensitive value."
            )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ag_operator_review_case_evidence_admission_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        cleanup = evidence["cleanup"]
        return (
            "ag_operator_review_case_evidence_admission_postgres_smoke=pass "
            f"service={evidence['service']} "
            f"db_env={evidence['database_env']} "
            f"target_id={evidence['target_id']} "
            f"cases={evidence['observations']['case_count']} "
            f"notes={evidence['observations']['note_count']} "
            f"exports={evidence['observations']['export_count']} "
            f"deleted_cases={cleanup['cases']} "
            f"deleted_notes={cleanup['notes']} "
            f"deleted_exports={cleanup['exports']}"
        )
    return (
        "ag_operator_review_case_evidence_admission_postgres_smoke=fail "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AG operator review case evidence/admission PostgreSQL smoke."
        )
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ag_operator_review_case_evidence_admission_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
