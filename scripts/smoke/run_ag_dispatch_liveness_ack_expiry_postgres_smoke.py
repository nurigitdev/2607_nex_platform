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

from nex_ag.liveness_ack_expiry_reconciliation import (  # noqa: E402
    run_operator_review_liveness_ack_expiry_reconciliation,
)
from nex_ag.operator_review_liveness_ack import (  # noqa: E402
    OperatorReviewLivenessAckStateError,
    SqlAlchemyOperatorReviewLivenessAckStateStore,
    apply_operator_review_liveness_ack_expiry_reconciliation,
    build_operator_review_liveness_ack_state_record,
)
from nex_runtime import (  # noqa: E402
    build_engine,
    build_session_factory,
    load_env_file,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ag_dispatch_liveness_ack_expiry_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_DISPATCH_LIVENESS_ACK_EXPIRY_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
SERVICE_ID = "nex-ag"
PROFILE = "test"
TABLE_NAME = "ag_op_review_ack_state"
INDEX_NAME = "idx_ag_ack_state_expiry"
MIGRATION_VERSION = "0813_ag_ack_expiry_index"


class _SingleCandidateStore:
    def __init__(self, delegate: Any, candidate: dict[str, Any] | None) -> None:
        self._delegate = delegate
        self._candidate = candidate

    def list_expiry_candidates(
        self,
        *,
        observed_at: object,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        del observed_at, limit
        return [self._candidate] if self._candidate is not None else []

    def apply_expiry_reconciliation(
        self,
        state: dict[str, Any],
        *,
        expected_updated_at: object,
    ) -> bool:
        return self._delegate.apply_expiry_reconciliation(
            state,
            expected_updated_at=expected_updated_at,
        )


def run_ag_dispatch_liveness_ack_expiry_postgres_smoke(
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

    engine: Any | None = None
    store: Any | None = None
    owned_ids: list[str] = []
    cleanup_done = False
    try:
        engine = build_engine(database_url)
        store = SqlAlchemyOperatorReviewLivenessAckStateStore(
            build_session_factory(engine)
        )
        evidence = _run_smoke(
            engine,
            store,
            migration=migration,
            database_url=database_url,
            owned_ids=owned_ids,
        )
        cleanup = _cleanup_owned_rows(store, owned_ids)
        cleanup_done = True
        evidence["cleanup"] = cleanup
        evidence["checks"]["owned_rows_deleted"] = (
            cleanup["deleted_rows"] == len(owned_ids)
            and cleanup["remaining_rows"] == 0
        )
        passed = all(evidence["checks"].values())
        evidence["status"] = "PASS" if passed else "FAIL"
        evidence["failure_code"] = None if passed else "checks_failed"
    except (
        OperatorReviewLivenessAckStateError,
        SQLAlchemyError,
        ValueError,
    ) as exc:
        evidence = _failure(
            "smoke_execution_failed",
            _redact_detail(str(exc), database_url=database_url),
        )
    finally:
        if store is not None and not cleanup_done:
            _cleanup_owned_rows(store, owned_ids)
        if engine is not None:
            engine.dispose()
    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _run_smoke(
    engine: Any,
    store: Any,
    *,
    migration: Any,
    database_url: str,
    owned_ids: list[str],
) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    observed_at = datetime.now(UTC).replace(microsecond=0)
    expired_at = datetime(2000, 1, 1, tzinfo=UTC)
    target = _smoke_state(
        suffix=suffix,
        purpose="apply",
        updated_at=expired_at,
        suppressed_until=expired_at + timedelta(minutes=5),
    )
    conflict = _smoke_state(
        suffix=suffix,
        purpose="conflict",
        updated_at=expired_at + timedelta(seconds=1),
        suppressed_until=expired_at + timedelta(minutes=6),
    )
    for state in (target, conflict):
        owned_ids.append(str(state["ack_state_id"]))
        store.save(state)

    selected = store.list_expiry_candidates(observed_at=observed_at, limit=200)
    target_candidate = _candidate_by_id(selected, target["ack_state_id"])
    conflict_candidate = _candidate_by_id(selected, conflict["ack_state_id"])
    run = run_operator_review_liveness_ack_expiry_reconciliation(
        _SingleCandidateStore(store, target_candidate),
        observed_at=observed_at,
        limit=10,
    )
    persisted_target = store.get(target["ack_state_id"])

    selected_after = store.list_expiry_candidates(
        observed_at=observed_at,
        limit=200,
    )
    rerun = run_operator_review_liveness_ack_expiry_reconciliation(
        _SingleCandidateStore(
            store,
            _candidate_by_id(selected_after, target["ack_state_id"]),
        ),
        observed_at=observed_at,
        limit=10,
    )

    conflict_mutation = (
        apply_operator_review_liveness_ack_expiry_reconciliation(
            conflict_candidate,
            observed_at=observed_at,
        )
        if conflict_candidate is not None
        else None
    )
    renewed = _smoke_state(
        suffix=suffix,
        purpose="conflict",
        updated_at=observed_at + timedelta(seconds=1),
        suppressed_until=observed_at + timedelta(hours=1),
    )
    store.save(renewed)
    stale_cas_applied = (
        store.apply_expiry_reconciliation(
            conflict_mutation["state"],
            expected_updated_at=conflict_mutation["candidate"][
                "expected_updated_at"
            ],
        )
        if conflict_mutation is not None
        else False
    )
    persisted_conflict = store.get(conflict["ack_state_id"])
    database = _database_observations(engine)
    checks = {
        "migration_ran": migration.service_id == SERVICE_ID,
        "backend_is_postgresql": _engine_backend(engine).startswith("postgresql"),
        "test_database_selected": _engine_database(engine) == "nex_ag_test",
        "table_present": database["table_present"],
        "expiry_index_present": database["expiry_index_present"],
        "migration_recorded": database["migration_recorded"],
        "sql_candidates_selected": (
            target_candidate is not None and conflict_candidate is not None
        ),
        "worker_applied_once": (
            run["candidate_count"] == 1
            and run["applied_count"] == 1
            and run["conflict_count"] == 0
        ),
        "expired_state_persisted": (
            persisted_target is not None
            and persisted_target["state_status"] == "EXPIRED"
            and persisted_target["metadata"]["last_expiry_reconciliation"][
                "reason"
            ]
            == "suppression_expired"
        ),
        "rerun_is_idempotent": (
            rerun["candidate_count"] == 0 and rerun["applied_count"] == 0
        ),
        "stale_cas_rejected": stale_cas_applied is False,
        "renewed_state_preserved": (
            persisted_conflict is not None
            and persisted_conflict["state_status"] == "SUPPRESSED"
            and persisted_conflict["updated_at"] == renewed["updated_at"]
            and persisted_conflict["suppressed_until"]
            == renewed["suppressed_until"]
        ),
    }
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "PENDING",
        "failure_code": None,
        "service": SERVICE_ID,
        "profile": PROFILE,
        "database_env": DATABASE_ENV,
        "redacted_database_url": redact_database_url(database_url),
        "migration": {
            "planned": list(migration.planned),
            "applied": list(migration.applied),
            "skipped": list(migration.skipped),
        },
        "database": database,
        "candidate_selection": {
            "selected_count": len(selected),
            "target_selected": target_candidate is not None,
            "conflict_selected": conflict_candidate is not None,
        },
        "reconciliation": _run_summary(run),
        "idempotent_rerun": _run_summary(rerun),
        "conflict_probe": {
            "stale_cas_applied": stale_cas_applied,
            "persisted_state_status": (
                persisted_conflict.get("state_status")
                if persisted_conflict is not None
                else None
            ),
            "renewed_deadline_preserved": checks["renewed_state_preserved"],
        },
        "checks": checks,
    }


def _smoke_state(
    *,
    suffix: str,
    purpose: str,
    updated_at: datetime,
    suppressed_until: datetime,
) -> dict[str, Any]:
    return build_operator_review_liveness_ack_state_record(
        ack_state_id=f"ack-smoke-0818-{purpose}-{suffix}",
        acknowledgement_key=f"nex-ag:smoke-0818-{purpose}-{suffix}:stale",
        service_id=SERVICE_ID,
        worker_id=f"smoke-0818-{purpose}-{suffix}",
        worker_type="operator_review_dispatch_daemon",
        liveness_status="STALE",
        action="suppress_for_ttl",
        state_status="SUPPRESSED",
        operator_ref={
            "operator_type": "service",
            "operator_id": "postgres-smoke-0818",
        },
        reason_codes=["smoke_0818_expiry_reconciliation"],
        requested_ttl_seconds=300,
        suppressed_until=suppressed_until,
        metadata={"source": "postgres_smoke", "slice": "0818"},
        created_at=updated_at,
        updated_at=updated_at,
    )


def _candidate_by_id(
    candidates: list[dict[str, Any]],
    ack_state_id: object,
) -> dict[str, Any] | None:
    return next(
        (
            candidate
            for candidate in candidates
            if candidate.get("ack_state_id") == ack_state_id
        ),
        None,
    )


def _database_observations(engine: Any) -> dict[str, Any]:
    with engine.begin() as connection:
        row = (
            connection.execute(
                text(
                    """
                    SELECT current_database() AS database_name,
                           to_regclass('public.ag_op_review_ack_state')::text
                               AS table_regclass,
                           to_regclass('public.idx_ag_ack_state_expiry')::text
                               AS index_regclass,
                           EXISTS (
                               SELECT 1
                               FROM schema_migrations
                               WHERE version = :migration_version
                           ) AS migration_recorded
                    """
                ),
                {"migration_version": MIGRATION_VERSION},
            )
            .mappings()
            .one()
        )
    return {
        "backend": _engine_backend(engine),
        "database": str(row.get("database_name") or ""),
        "table_name": TABLE_NAME,
        "table_present": _regclass_matches(row.get("table_regclass"), TABLE_NAME),
        "index_name": INDEX_NAME,
        "expiry_index_present": _regclass_matches(
            row.get("index_regclass"), INDEX_NAME
        ),
        "migration_version": MIGRATION_VERSION,
        "migration_recorded": bool(row.get("migration_recorded")),
    }


def _cleanup_owned_rows(store: Any, owned_ids: list[str]) -> dict[str, int]:
    deleted = sum(store.delete(ack_state_id) for ack_state_id in owned_ids)
    remaining = sum(store.get(ack_state_id) is not None for ack_state_id in owned_ids)
    return {"deleted_rows": deleted, "remaining_rows": remaining}


def _run_summary(run: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "run_status": run.get("run_status"),
        "candidate_count": run.get("candidate_count"),
        "applied_count": run.get("applied_count"),
        "conflict_count": run.get("conflict_count"),
        "skipped_count": run.get("skipped_count"),
        "outcome_statuses": [
            outcome.get("status")
            for outcome in run.get("outcomes", [])
            if isinstance(outcome, Mapping)
        ],
    }


def _regclass_matches(value: object, expected: str) -> bool:
    return str(value or "").rsplit(".", 1)[-1] == expected


def _engine_backend(engine: Any) -> str:
    url = getattr(engine, "url", None)
    get_backend_name = getattr(url, "get_backend_name", None)
    return str(get_backend_name()) if callable(get_backend_name) else "unknown"


def _engine_database(engine: Any) -> str | None:
    database = getattr(getattr(engine, "url", None), "database", None)
    return str(database) if database else None


def _redact_detail(detail: str, *, database_url: str) -> str:
    return detail.replace(database_url, redact_database_url(database_url))


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    env: Mapping[str, str],
) -> None:
    database_url = env.get(DATABASE_ENV, "")
    if database_url and database_url in serialized_evidence:
        raise ValueError("smoke evidence contains an unredacted database URL")


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
        return f"ag_dispatch_liveness_ack_expiry_postgres_smoke=skipped reason={SMOKE_ENV}"
    if status != "pass":
        return (
            "ag_dispatch_liveness_ack_expiry_postgres_smoke=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    database = evidence.get("database", {})
    reconciliation = evidence.get("reconciliation", {})
    cleanup = evidence.get("cleanup", {})
    return (
        "ag_dispatch_liveness_ack_expiry_postgres_smoke=pass "
        f"database={database.get('database')} "
        f"backend={database.get('backend')} "
        f"applied={reconciliation.get('applied_count')} "
        f"deleted_rows={cleanup.get('deleted_rows')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    load_env_file(Path(args.env_file))
    evidence = run_ag_dispatch_liveness_ack_expiry_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
