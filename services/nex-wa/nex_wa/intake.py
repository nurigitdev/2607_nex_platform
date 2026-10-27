from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from nex_runtime import JobQueue, JobQueueError, build_common_job, build_subject_ref

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
    ) -> None:
        self._job_queue = job_queue
        self._clock = clock or (lambda: datetime.now(UTC))

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
            return build_evidence_intake_admission(
                request,
                request_id=request_id,
                trace_id=trace_id,
                idempotent_reuse=(stored.get("request_id") != request_id),
            )
        except WaIntakeContractError:
            raise
        except JobQueueError as exc:
            raise WaIntakeContractError(
                "WA_INTAKE_STORE_UNAVAILABLE",
                "evidence intake persistence is unavailable",
                503,
            ) from exc

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
