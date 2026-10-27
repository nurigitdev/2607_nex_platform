from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import admit_service_token_from_request, problem_response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

SERVICE_ID = "nex-wa"
WA_OPERATIONS_READ_SCOPE = "work:operations:read"
WA_OPERATIONS_SCHEMA = "wa_operations_summary.v1"


class WaOperationsError(Exception):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


class SqlAlchemyWaOperationsSource:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
        heartbeat_stale_after_seconds: int = 60,
    ) -> None:
        if heartbeat_stale_after_seconds < 1:
            raise ValueError("heartbeat stale threshold must be positive")
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._heartbeat_stale_after_seconds = heartbeat_stale_after_seconds

    def snapshot(self) -> dict[str, Any]:
        observed_at = _aware(self._clock())
        try:
            with self._session_factory() as session:
                status_rows = session.execute(
                    text(
                        "SELECT status, count(*) AS count, "
                        "MIN(CASE WHEN status = 'QUEUED' THEN available_at END) "
                        "AS oldest_runnable_at "
                        "FROM service_jobs WHERE job_type = 'WA_EVIDENCE_INGEST' "
                        "GROUP BY status"
                    )
                ).mappings().all()
                heartbeats = session.execute(
                    text(
                        "SELECT status, last_seen_at FROM service_worker_heartbeats "
                        "WHERE service_id = :service_id"
                    ),
                    {"service_id": SERVICE_ID},
                ).mappings().all()
                events = session.execute(
                    text(
                        "SELECT event_type, count(*) AS count "
                        "FROM service_operational_events "
                        "WHERE service_id = :service_id GROUP BY event_type"
                    ),
                    {"service_id": SERVICE_ID},
                ).mappings().all()
                dead_letter_count = session.execute(
                    text(
                        "SELECT count(*) FROM service_jobs "
                        "WHERE job_type = 'WA_EVIDENCE_INGEST' "
                        "AND status = 'FAILED' AND retryable = false"
                    )
                ).scalar_one()
        except SQLAlchemyError as exc:
            raise WaOperationsError(
                "WA_OPERATIONS_UNAVAILABLE",
                "WA operational projection is unavailable",
            ) from exc

        jobs = {str(row["status"]): int(row["count"]) for row in status_rows}
        oldest_candidates = [
            _aware(row["oldest_runnable_at"])
            for row in status_rows
            if row["oldest_runnable_at"] is not None
        ]
        oldest_age = (
            None
            if not oldest_candidates
            else max(0.0, (observed_at - min(oldest_candidates)).total_seconds())
        )
        event_counts = {str(row["event_type"]): int(row["count"]) for row in events}
        heartbeat_statuses: dict[str, int] = {}
        stale_count = 0
        for row in heartbeats:
            status = str(row["status"])
            heartbeat_statuses[status] = heartbeat_statuses.get(status, 0) + 1
            age = (observed_at - _aware(row["last_seen_at"])).total_seconds()
            stale_count += int(age > self._heartbeat_stale_after_seconds)

        return {
            "schema_version": WA_OPERATIONS_SCHEMA,
            "service_id": SERVICE_ID,
            "observed_at": _wire(observed_at),
            "queue": {
                "queued": jobs.get("QUEUED", 0),
                "running": jobs.get("RUNNING", 0),
                "succeeded": jobs.get("SUCCEEDED", 0),
                "failed": jobs.get("FAILED", 0),
                "dead_lettered": int(dead_letter_count),
                "oldest_runnable_age_seconds": oldest_age,
            },
            "outcomes": {
                "ingest_success": jobs.get("SUCCEEDED", 0),
                "ingest_failure": jobs.get("FAILED", 0),
                "source_hash_conflict": event_counts.get("wa.source.conflict", 0),
                "evidence_reuse": event_counts.get("wa.evidence.reused", 0),
                "stale_recovery": event_counts.get("wa.job.stale_recovered", 0),
                "reconciliation_completed": event_counts.get(
                    "wa.reconciliation.completed", 0
                ),
            },
            "consumer": {
                "heartbeat_count": sum(heartbeat_statuses.values()),
                "stale_count": stale_count,
                "status_counts": heartbeat_statuses,
                "stale_after_seconds": self._heartbeat_stale_after_seconds,
            },
        }


def register_wa_operations_routes(
    app: FastAPI,
    *,
    source: SqlAlchemyWaOperationsSource | None,
) -> None:
    app.state.wa_operations_source = source

    @app.get("/internal/v1/operations/summary", response_model=None)
    def get_wa_operations_summary(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | JSONResponse:
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience=SERVICE_ID,
            required_scopes=("service:call", WA_OPERATIONS_READ_SCOPE),
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        if admitted.service_id != "nex-ag":
            return _problem(request, 403, "WA_OPERATIONS_CALLER_FORBIDDEN")
        if source is None:
            return _problem(request, 503, "WA_OPERATIONS_UNAVAILABLE", retryable=True)
        try:
            return source.snapshot()
        except WaOperationsError as exc:
            return _problem(request, 503, exc.error_code, retryable=True)


def _problem(
    request: Request,
    status_code: int,
    error_code: str,
    *,
    retryable: bool = False,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=status_code,
        error_code=error_code,
        title="WA operations request failed",
        detail="WA operational projection request was not admitted.",
        retryable=retryable,
        type_uri="https://nex-platform.local/problems/wa-operations",
    )


def _aware(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise WaOperationsError(
            "WA_OPERATIONS_TIMESTAMP_INVALID",
            "WA operational timestamp is invalid",
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _wire(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
