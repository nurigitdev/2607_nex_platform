from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from nex_runtime import (
    JobQueue,
    JobQueueError,
    OperationalEventEmitter,
    build_common_job,
    build_subject_ref,
)

from .intake_contracts import (
    WA_EVIDENCE_INGEST_JOB_TYPE,
    WaEvidenceIntakeAdmission,
    WaEvidenceIntakeRequest,
    WaIntakeContractError,
    build_evidence_intake_admission,
    build_evidence_intake_identity,
    normalize_evidence_intake_request,
    require_compatible_intake_replay,
)

WA_EVIDENCE_INGEST_SCOPE = "work:evidence:ingest"
WA_EVIDENCE_INGEST_MAX_ATTEMPTS = 5


class WaEvidenceIntakeService:
    def __init__(
        self,
        job_queue: JobQueue,
        *,
        clock: Callable[[], datetime] | None = None,
        event_emitter: OperationalEventEmitter | None = None,
    ) -> None:
        self._job_queue = job_queue
        self._clock = clock or (lambda: datetime.now(UTC))
        self._event_emitter = event_emitter

    def admit(
        self,
        value: Mapping[str, Any],
        *,
        caller_service_id: str,
        request_id: str,
        trace_id: str,
    ) -> WaEvidenceIntakeAdmission:
        normalized = normalize_evidence_intake_request(value)
        request = replace(
            normalized,
            request_id=request_id,
            trace_id=trace_id,
        )
        identity = build_evidence_intake_identity(request)
        try:
            existing = self._job_queue.get_job(identity.job_id)
            if existing is not None:
                self._require_stored_replay(existing, request)
                self._emit(
                    "wa.evidence.reused",
                    request,
                    request_id=request_id,
                    trace_id=trace_id,
                    status="REUSED",
                )
                return build_evidence_intake_admission(
                    request,
                    request_id=request_id,
                    trace_id=trace_id,
                    idempotent_reuse=True,
                )

            job = build_common_job(
                job_id=identity.job_id,
                job_type=WA_EVIDENCE_INGEST_JOB_TYPE,
                trace_id=trace_id,
                request_id=request_id,
                subject_ref=build_subject_ref("SERVICE", caller_service_id),
                idempotency_key=identity.idempotency_key,
                created_at=_wire_timestamp(self._clock()),
                max_attempts=WA_EVIDENCE_INGEST_MAX_ATTEMPTS,
                retryable=True,
                links={"correlation_id": request.correlation_id},
            )
            job["payload"] = request.to_job_payload()
            stored = self._job_queue.enqueue(job)
            self._require_stored_replay(stored, request)
            self._emit(
                "wa.intake.admitted",
                request,
                request_id=request_id,
                trace_id=trace_id,
                status="QUEUED",
            )
            return build_evidence_intake_admission(
                request,
                request_id=request_id,
                trace_id=trace_id,
                idempotent_reuse=(stored.get("request_id") != request_id),
            )
        except WaIntakeContractError as exc:
            if exc.error_code == "WA_SOURCE_IDEMPOTENCY_CONFLICT":
                self._emit(
                    "wa.source.conflict",
                    request,
                    request_id=request_id,
                    trace_id=trace_id,
                    status="REJECTED",
                    error_code=exc.error_code,
                )
            raise
        except JobQueueError as exc:
            raise WaIntakeContractError(
                "WA_INTAKE_STORE_UNAVAILABLE",
                "evidence intake persistence is unavailable",
                503,
            ) from exc

    def _emit(
        self,
        event_type: str,
        request: WaEvidenceIntakeRequest,
        *,
        request_id: str,
        trace_id: str,
        status: str,
        error_code: str | None = None,
    ) -> None:
        if self._event_emitter is None:
            return
        details = {"source_type": request.source_type, "status": status}
        if error_code is not None:
            details["error_code"] = error_code
        self._event_emitter.safe_emit(
            event_type=event_type,
            severity="WARNING" if error_code else "INFO",
            message="WA evidence intake lifecycle changed.",
            trace_id=trace_id,
            request_id=request_id,
            subject_ref={"type": "wa.source", "id": request.source_ref},
            details=details,
            created_at=_wire_timestamp(self._clock()),
        )

    @staticmethod
    def _require_stored_replay(
        job: Mapping[str, Any],
        candidate: WaEvidenceIntakeRequest,
    ) -> None:
        if job.get("job_type") != WA_EVIDENCE_INGEST_JOB_TYPE:
            raise WaIntakeContractError(
                "WA_INTAKE_STORE_INVALID",
                "stored intake Job has an invalid type",
                503,
            )
        payload = job.get("payload")
        if not isinstance(payload, Mapping):
            raise WaIntakeContractError(
                "WA_INTAKE_STORE_INVALID",
                "stored intake Job payload is invalid",
                503,
            )
        try:
            existing = normalize_evidence_intake_request(payload)
        except WaIntakeContractError as exc:
            raise WaIntakeContractError(
                "WA_INTAKE_STORE_INVALID",
                "stored intake Job payload is invalid",
                503,
            ) from exc
        require_compatible_intake_replay(existing, candidate)


def _wire_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("WA intake clock must return a timezone-aware datetime")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
