#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))

from nex_ag.operations import (  # noqa: E402
    OperationsQueryError,
    build_operator_review_escalation_dispatch_daemon_liveness_projection,
    build_operator_review_escalation_dispatch_daemon_liveness_recovery_plan,
)
from nex_ag.operator_review_dispatch_execution import (  # noqa: E402
    DISPATCH_EXECUTION_DAEMON_HEARTBEAT_SERVICE_ID,
    DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
)
from nex_ag.operator_review_liveness_ack import (  # noqa: E402
    SqlAlchemyOperatorReviewLivenessAckStateStore,
    acknowledgement_key_for_liveness,
    apply_operator_review_liveness_ack_state_transition,
)
from nex_runtime import (  # noqa: E402
    SqlAlchemyWorkerHeartbeatStore,
    build_engine,
    build_session_factory,
    build_worker_heartbeat,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = (
    "ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke.v1"
)
SMOKE_ENV = (
    "NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_LIVENESS_ACK_STATE_POSTGRES_SMOKE"
)
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
WORKER_ID = "ag-dispatch-execution-daemon"
STALE_AFTER_SECONDS = 60
RAW_IDEMPOTENCY_SECRET = "raw-idempotency-secret-0808"


def run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke(
    environ: Mapping[str, str] | None = None,
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
        return _failure(
            "migration_failed",
            _redact_detail(str(exc), database_url=database_url),
        )

    suffix = uuid4().hex[:12]
    request_id = f"ag-dispatch-daemon-liveness-ack-state-smoke-{suffix}"
    trace_id = uuid4().hex
    checked_at = datetime.now(UTC).replace(microsecond=0)
    engine: Any | None = None
    heartbeat_store: Any | None = None
    ack_state_store: Any | None = None
    original_heartbeat: dict[str, Any] | None = None
    original_ack_state: dict[str, Any] | None = None
    ack_state_id: str | None = None
    cleanup_done = False
    try:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        heartbeat_store = SqlAlchemyWorkerHeartbeatStore(session_factory)
        ack_state_store = SqlAlchemyOperatorReviewLivenessAckStateStore(
            session_factory
        )
        original_heartbeat = heartbeat_store.get_heartbeat(SERVICE_ID, WORKER_ID)
        acknowledgement_key = acknowledgement_key_for_liveness(
            service_id=SERVICE_ID,
            worker_id=WORKER_ID,
            liveness_status="STALE",
        )
        original_ack_state = ack_state_store.get_by_acknowledgement_key(
            acknowledgement_key
        )

        stale_heartbeat = _smoke_heartbeat(
            suffix=suffix,
            trace_id=trace_id,
            last_seen_at=checked_at - timedelta(seconds=STALE_AFTER_SECONDS + 30),
        )
        heartbeat_store.upsert_heartbeat(stale_heartbeat)
        liveness_projection = (
            build_operator_review_escalation_dispatch_daemon_liveness_projection(
                worker_heartbeat_stores={SERVICE_ID: heartbeat_store},
                worker_id=WORKER_ID,
                stale_after_seconds=STALE_AFTER_SECONDS,
                checked_at=_to_zulu(checked_at),
                request_trace_id=trace_id,
            )
        )

        mutation = apply_operator_review_liveness_ack_state_transition(
            original_ack_state,
            service_id=SERVICE_ID,
            worker_id=WORKER_ID,
            worker_type=DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
            liveness_status="STALE",
            action="suppress_for_ttl",
            operator_ref={
                "operator_type": "service",
                "operator_id": "postgres-smoke-0808",
                "tenant_id": "nex-platform",
            },
            reason_codes=["smoke_0808_liveness_ack_state"],
            comment="Slice 0808 PostgreSQL acknowledgement state smoke.",
            idempotency_key=RAW_IDEMPOTENCY_SECRET,
            requested_ttl_seconds=300,
            observed_at=checked_at,
            metadata={
                "source": "postgres_smoke",
                "slice": "0808",
                "smoke_id": suffix,
                "trace_id": trace_id,
                "secret_included": False,
            },
        )
        saved_state = ack_state_store.save(mutation["state"])
        ack_state_id = str(saved_state["ack_state_id"])
        fetched_by_id = ack_state_store.get(ack_state_id)
        fetched_by_key = ack_state_store.get_by_acknowledgement_key(
            acknowledgement_key
        )
        listed_states = ack_state_store.list_states(
            service_id=SERVICE_ID,
            worker_id=WORKER_ID,
            liveness_status="STALE",
            state_status="SUPPRESSED",
            limit=10,
        )
        recovery_plan = build_operator_review_escalation_dispatch_daemon_liveness_recovery_plan(
            liveness_projection,
            process_section={
                "process_control_path": (
                    "/admin/v1/operator-review/dispatch-daemon/process-controls"
                )
            },
            ack_state_store=ack_state_store,
            checked_at=_to_zulu(checked_at),
            request_trace_id=trace_id,
        )
        overlay = recovery_plan.get("acknowledgement_state_overlay", {})
        suppressed_observations = _db_ack_state_observations(
            engine,
            ack_state_id=ack_state_id,
        )

        clear_mutation = apply_operator_review_liveness_ack_state_transition(
            saved_state,
            service_id=SERVICE_ID,
            worker_id=WORKER_ID,
            worker_type=DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
            liveness_status="STALE",
            action="clear",
            operator_ref={
                "operator_type": "service",
                "operator_id": "postgres-smoke-0808",
                "tenant_id": "nex-platform",
            },
            reason_codes=["smoke_0808_liveness_ack_state_clear"],
            comment="Slice 0808 PostgreSQL acknowledgement state clear.",
            idempotency_key=f"clear-{RAW_IDEMPOTENCY_SECRET}",
            observed_at=checked_at + timedelta(seconds=1),
            metadata={
                "source": "postgres_smoke",
                "slice": "0808",
                "smoke_id": suffix,
                "trace_id": trace_id,
                "secret_included": False,
            },
        )
        cleared_state = ack_state_store.save(clear_mutation["state"])
        fetched_cleared_state = ack_state_store.get(ack_state_id)
        cleared_observations = _db_ack_state_observations(
            engine,
            ack_state_id=ack_state_id,
        )

        liveness_summary = liveness_projection.get("summary", {})
        overlay_effective = (
            overlay.get("effective_status")
            if isinstance(overlay.get("effective_status"), Mapping)
            else {}
        )
        listed_ids = {str(state.get("ack_state_id")) for state in listed_states}
        checks = {
            "migration_ran": migration.service_id == SERVICE_ID,
            "backend_is_postgresql": _engine_backend(engine).startswith("postgresql"),
            "ack_state_table_used": (
                suppressed_observations.get("table_name")
                == "ag_op_review_ack_state"
            ),
            "ack_state_row_persisted": (
                suppressed_observations.get("row_count") == 1
            ),
            "saved_state_suppressed": (
                saved_state.get("state_status") == "SUPPRESSED"
                and saved_state.get("action") == "suppress_for_ttl"
            ),
            "get_by_id_round_trip": (
                fetched_by_id is not None
                and fetched_by_id.get("ack_state_id") == ack_state_id
            ),
            "get_by_key_round_trip": (
                fetched_by_key is not None
                and fetched_by_key.get("acknowledgement_key") == acknowledgement_key
            ),
            "list_round_trip": ack_state_id in listed_ids,
            "liveness_projection_stale": (
                liveness_projection.get("projection_status") == "READY"
                and liveness_summary.get("liveness_status") == "STALE"
            ),
            "recovery_overlay_reads_persisted_state": (
                overlay.get("overlay_status") == "STATE_PRESENT"
                and overlay.get("ack_state_id") == ack_state_id
                and overlay.get("source_projection_suppressed") is False
                and overlay_effective.get("effective_state_status")
                == "SUPPRESSED"
            ),
            "clear_round_trip": (
                cleared_state.get("state_status") == "CLEARED"
                and fetched_cleared_state is not None
                and fetched_cleared_state.get("state_status") == "CLEARED"
                and cleared_observations.get("state_statuses") == ["CLEARED"]
            ),
            "raw_idempotency_not_persisted": (
                suppressed_observations.get("raw_value_leak_count") == 0
                and cleared_observations.get("raw_value_leak_count") == 0
            ),
        }
        cleanup = _cleanup_smoke_rows(
            heartbeat_store,
            ack_state_store,
            engine,
            original_heartbeat=original_heartbeat,
            original_ack_state=original_ack_state,
            ack_state_id=ack_state_id,
        )
        cleanup_done = True
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
            "worker_id": WORKER_ID,
            "ack_state_id": ack_state_id,
            "acknowledgement_key": acknowledgement_key,
            "liveness_summary": liveness_summary,
            "mutation": _mutation_summary(mutation),
            "clear_mutation": _mutation_summary(clear_mutation),
            "recovery_overlay": _overlay_summary(overlay),
            "suppressed_observations": suppressed_observations,
            "cleared_observations": cleared_observations,
            "checks": checks,
            "cleanup": cleanup,
        }
    except (
        OperationsQueryError,
        SQLAlchemyError,
        ValueError,
    ) as exc:
        evidence = _failure(
            "smoke_execution_failed",
            _redact_detail(str(exc), database_url=database_url),
        )
    finally:
        if engine is not None:
            if (
                not cleanup_done
                and heartbeat_store is not None
                and ack_state_store is not None
            ):
                _cleanup_smoke_rows(
                    heartbeat_store,
                    ack_state_store,
                    engine,
                    original_heartbeat=original_heartbeat,
                    original_ack_state=original_ack_state,
                    ack_state_id=ack_state_id,
                )
            engine.dispose()
    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _smoke_heartbeat(
    *,
    suffix: str,
    trace_id: str,
    last_seen_at: datetime,
) -> dict[str, Any]:
    started_at = last_seen_at - timedelta(seconds=15)
    return build_worker_heartbeat(
        service_id=DISPATCH_EXECUTION_DAEMON_HEARTBEAT_SERVICE_ID,
        worker_id=WORKER_ID,
        worker_type=DISPATCH_EXECUTION_DAEMON_HEARTBEAT_WORKER_TYPE,
        status="IDLE",
        trace_id=trace_id,
        started_at=_to_zulu(started_at),
        last_seen_at=_to_zulu(last_seen_at),
        metadata={
            "source": "postgres_smoke",
            "slice": "0808",
            "smoke_id": suffix,
            "secret_included": False,
        },
    )


def _db_ack_state_observations(
    engine: Any,
    *,
    ack_state_id: str,
) -> dict[str, Any]:
    with engine.begin() as connection:
        rows = list(
            connection.execute(
                text(
                    """
                    SELECT ack_state_id,
                           acknowledgement_key,
                           service_id,
                           worker_id,
                           liveness_status,
                           action,
                           state_status,
                           comment_preview,
                           comment_hash,
                           idempotency_key_hash,
                           metadata::text AS metadata_text
                    FROM ag_op_review_ack_state
                    WHERE ack_state_id = :ack_state_id
                    """
                ),
                {"ack_state_id": ack_state_id},
            ).mappings()
        )
    raw_value_leak_count = 0
    state_statuses: list[str] = []
    actions: list[str] = []
    comment_hash_present = False
    idempotency_hash_present = False
    for row in rows:
        state_statuses.append(str(row.get("state_status") or ""))
        actions.append(str(row.get("action") or ""))
        comment_hash_present = comment_hash_present or bool(row.get("comment_hash"))
        idempotency_hash_present = idempotency_hash_present or bool(
            row.get("idempotency_key_hash")
        )
        for value in (
            row.get("idempotency_key_hash"),
            row.get("metadata_text"),
        ):
            if RAW_IDEMPOTENCY_SECRET in str(value or ""):
                raw_value_leak_count += 1
    return {
        "table_name": "ag_op_review_ack_state",
        "row_count": len(rows),
        "backend": _engine_backend(engine),
        "database": _engine_database(engine),
        "state_statuses": sorted(status for status in state_statuses if status),
        "actions": sorted(action for action in actions if action),
        "comment_hash_present": comment_hash_present,
        "idempotency_key_hash_present": idempotency_hash_present,
        "raw_value_leak_count": raw_value_leak_count,
    }


def _cleanup_smoke_rows(
    heartbeat_store: Any,
    ack_state_store: Any,
    engine: Any,
    *,
    original_heartbeat: dict[str, Any] | None,
    original_ack_state: dict[str, Any] | None,
    ack_state_id: str | None,
) -> dict[str, Any]:
    return {
        **_restore_or_delete_heartbeat(
            heartbeat_store,
            engine,
            original_heartbeat=original_heartbeat,
        ),
        **_restore_or_delete_ack_state(
            ack_state_store,
            engine,
            original_ack_state=original_ack_state,
            ack_state_id=ack_state_id,
        ),
    }


def _restore_or_delete_heartbeat(
    heartbeat_store: Any,
    engine: Any,
    *,
    original_heartbeat: dict[str, Any] | None,
) -> dict[str, Any]:
    if original_heartbeat is not None:
        heartbeat_store.upsert_heartbeat(original_heartbeat)
        return {
            "restored_original_heartbeat": True,
            "deleted_heartbeat_rows": 0,
        }
    return {
        "restored_original_heartbeat": False,
        "deleted_heartbeat_rows": _delete_smoke_heartbeat(engine),
    }


def _restore_or_delete_ack_state(
    ack_state_store: Any,
    engine: Any,
    *,
    original_ack_state: dict[str, Any] | None,
    ack_state_id: str | None,
) -> dict[str, Any]:
    if original_ack_state is not None:
        ack_state_store.save(original_ack_state)
        return {
            "restored_original_ack_state": True,
            "deleted_ack_state_rows": 0,
        }
    if not ack_state_id:
        return {
            "restored_original_ack_state": False,
            "deleted_ack_state_rows": 0,
        }
    return {
        "restored_original_ack_state": False,
        "deleted_ack_state_rows": _delete_smoke_ack_state(
            engine,
            ack_state_id=ack_state_id,
        ),
    }


def _delete_smoke_heartbeat(engine: Any) -> int:
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                DELETE FROM service_worker_heartbeats
                WHERE service_id = :service_id AND worker_id = :worker_id
                """
            ),
            {"service_id": SERVICE_ID, "worker_id": WORKER_ID},
        )
    return int(result.rowcount or 0)


def _delete_smoke_ack_state(engine: Any, *, ack_state_id: str) -> int:
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                DELETE FROM ag_op_review_ack_state
                WHERE ack_state_id = :ack_state_id
                """
            ),
            {"ack_state_id": ack_state_id},
        )
    return int(result.rowcount or 0)


def _mutation_summary(mutation: Mapping[str, Any]) -> dict[str, Any]:
    transition = mutation.get("transition")
    state = mutation.get("state")
    transition_map = transition if isinstance(transition, Mapping) else {}
    state_map = state if isinstance(state, Mapping) else {}
    return {
        "mutation_status": mutation.get("mutation_status"),
        "action": transition_map.get("action"),
        "target_state_status": transition_map.get("target_state_status"),
        "ack_state_id": state_map.get("ack_state_id"),
        "state_status": state_map.get("state_status"),
        "raw_comment_stored": transition_map.get("guardrails", {}).get(
            "raw_comment_stored"
        )
        if isinstance(transition_map.get("guardrails"), Mapping)
        else None,
        "raw_idempotency_key_stored": transition_map.get("guardrails", {}).get(
            "raw_idempotency_key_stored"
        )
        if isinstance(transition_map.get("guardrails"), Mapping)
        else None,
    }


def _overlay_summary(overlay: object) -> dict[str, Any]:
    if not isinstance(overlay, Mapping):
        return {"present": False}
    effective = overlay.get("effective_status")
    effective_map = effective if isinstance(effective, Mapping) else {}
    return {
        "present": True,
        "overlay_status": overlay.get("overlay_status"),
        "ack_state_id": overlay.get("ack_state_id"),
        "state_status": overlay.get("state_status"),
        "effective_state_status": effective_map.get("effective_state_status"),
        "source_projection_suppressed": overlay.get("source_projection_suppressed"),
        "issue_candidate_suppressed": overlay.get("issue_candidate_suppressed"),
    }


def _to_zulu(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def _engine_backend(engine: Any) -> str:
    url = getattr(engine, "url", None)
    get_backend_name = getattr(url, "get_backend_name", None)
    if callable(get_backend_name):
        return str(get_backend_name())
    return "unknown"


def _engine_database(engine: Any) -> str | None:
    url = getattr(engine, "url", None)
    database = getattr(url, "database", None)
    return str(database) if database else None


def _redact_detail(detail: str, *, database_url: str) -> str:
    return detail.replace(database_url, redact_database_url(database_url))


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    env: Mapping[str, str],
) -> None:
    forbidden = [
        value
        for value in (
            RAW_IDEMPOTENCY_SECRET,
            env.get(DATABASE_ENV, ""),
        )
        if value
    ]
    leaked = [value for value in forbidden if value in serialized_evidence]
    if leaked:
        raise ValueError("smoke evidence contains unredacted sensitive value")


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status == "skipped":
        return (
            "ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_"
            f"postgres_smoke=skipped reason={SMOKE_ENV}"
        )
    if status != "pass":
        return (
            "ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_"
            f"postgres_smoke=fail failure={evidence.get('failure_code') or 'unknown'}"
        )
    suppressed = evidence.get("suppressed_observations", {})
    cleared = evidence.get("cleared_observations", {})
    cleanup = evidence.get("cleanup", {})
    overlay = evidence.get("recovery_overlay", {})
    return (
        "ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_"
        "postgres_smoke=pass "
        f"service={evidence.get('service')} "
        f"db_env={evidence.get('database_env')} "
        f"backend={suppressed.get('backend')} "
        f"rows={suppressed.get('row_count')} "
        f"overlay={overlay.get('overlay_status')} "
        f"cleared={','.join(cleared.get('state_statuses') or [])} "
        f"deleted_ack_state_rows={cleanup.get('deleted_ack_state_rows')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    load_env_file(Path(args.env_file))
    evidence = (
        run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke()
    )
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
