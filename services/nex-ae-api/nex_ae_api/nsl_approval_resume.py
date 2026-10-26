from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.nsl_approval_events import (
    NslApprovalEventError,
    validate_nsl_approval_event,
)
from nex_ae_api.nsl_approval_publication import NSL_APPROVAL_RESUME_CONTRACT_REF
from nex_ae_api.runtime_jobs import RuntimeJobClaim

_PAYLOAD_FIELDS = frozenset(
    {
        "wait_id",
        "event_id",
        "approval_request_id",
        "approval_work_item_ref",
        "approval_evidence_ref",
        "resume_token_ref",
    }
)


@dataclass(frozen=True)
class NslApprovalResumeError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class SqlAlchemyNslApprovalResumeSource:
    """Resolve the exact durable approval authority for one running resume job."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def resolve(self, claim: RuntimeJobClaim) -> Mapping[str, Any]:
        job, payload = _validate_claim(claim)
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(_AUTHORITY_SQL),
                        {
                            "tenant_id": job["tenant_id"],
                            "runtime_job_id": job["runtime_job_id"],
                        },
                    )
                    .mappings()
                    .first()
                )
        except SQLAlchemyError as exc:
            raise NslApprovalResumeError(
                "ae.nsl_approval_resume_store_unavailable",
                "NSL approval resume persistence is unavailable.",
                True,
            ) from exc
        if row is None:
            raise _authority_missing()
        return _project_authority(row, job=job, payload=payload)


def _validate_claim(
    claim: object,
) -> tuple[Mapping[str, Any], dict[str, str]]:
    if not isinstance(claim, RuntimeJobClaim):
        raise _invalid("NSL approval resume requires a RuntimeJobClaim.")
    job = claim.job
    attempt = claim.attempt
    raw_payload = job.get("payload")
    if (
        job.get("job_type") != "RESUME_EXECUTION"
        or job.get("state") != "RUNNING"
        or not isinstance(raw_payload, Mapping)
        or set(raw_payload) != _PAYLOAD_FIELDS
        or not isinstance(attempt, Mapping)
        or attempt.get("outcome") != "RUNNING"
    ):
        raise _invalid("RuntimeJob lacks exact running NSL approval resume authority.")
    payload = {
        field: _required(field, raw_payload.get(field)) for field in _PAYLOAD_FIELDS
    }
    if (
        _value(job.get("wait_id")) != payload["wait_id"]
        or _value(attempt.get("tenant_id")) != _value(job.get("tenant_id"))
        or _value(attempt.get("runtime_job_id")) != _value(job.get("runtime_job_id"))
        or _value(attempt.get("lease_token")) != _value(job.get("lease_token"))
        or _value(attempt.get("worker_id")) != _value(job.get("lease_owner"))
    ):
        raise _invalid("RuntimeJob claim lineage does not match its running attempt.")
    return job, payload


def _project_authority(
    row: Mapping[str, Any],
    *,
    job: Mapping[str, Any],
    payload: Mapping[str, str],
) -> dict[str, Any]:
    stored_payload = _mapping(row["job_payload"], "RuntimeJob payload")
    try:
        event = validate_nsl_approval_event(
            _mapping(row["event_payload"], "event payload")
        )
    except NslApprovalEventError as exc:
        raise _invalid("Stored NSL approval event is malformed.") from exc
    expected = {
        "job_state": "RUNNING",
        "job_type": "RESUME_EXECUTION",
        "job_execution_id": _value(job.get("execution_id")),
        "job_step_id": _value(job.get("executable_step_id")),
        "job_wait_id": payload["wait_id"],
        "job_lease_owner": _value(job.get("lease_owner")),
        "job_lease_token": _value(job.get("lease_token")),
        "wait_type": "NSL_APPROVAL",
        "wait_state": "RESUME_QUEUED",
        "wait_event_id": payload["event_id"],
        "wait_runtime_job_id": _value(job.get("runtime_job_id")),
        "wait_external_ref": payload["approval_request_id"],
        "wait_request_id": payload["approval_request_id"],
        "wait_result_contract_ref": NSL_APPROVAL_RESUME_CONTRACT_REF,
        "wait_execution_id": _value(job.get("execution_id")),
        "wait_step_id": _value(job.get("executable_step_id")),
        "step_executor_kind": "LOCAL_SKILL",
        "inbox_state": "MATCHED",
        "inbox_type": "NSL_APPROVAL_DECIDED",
        "inbox_event_id": payload["event_id"],
        "inbox_request_id": payload["approval_request_id"],
        "inbox_work_item_ref": payload["approval_work_item_ref"],
        "inbox_evidence_ref": payload["approval_evidence_ref"],
        "request_id": payload["approval_request_id"],
        "evidence_request_id": payload["approval_request_id"],
        "evidence_work_item_ref": payload["approval_work_item_ref"],
    }
    if any(_value(row.get(field)) != value for field, value in expected.items()):
        raise _authority_missing()
    if _value(row.get("step_state")) not in {"WAITING", "RUNNING"}:
        raise _authority_missing()
    if {key: _value(value) for key, value in stored_payload.items()} != dict(payload):
        raise _authority_missing()

    evidence_ref = f"ae-approval-evidence:{payload['approval_request_id']}"
    resume_token_ref = f"ae-nsl-resume:{_value(row['evidence_integrity'])}"
    shared = {
        "approval_request_id": payload["approval_request_id"],
        "approval_work_item_ref": payload["approval_work_item_ref"],
        "nsl_execution_id": _value(row["wait_nsl_execution_id"]),
        "business_operation_id": _value(row["wait_business_operation_id"]),
        "evidence_integrity": _value(row["evidence_integrity"]),
    }
    if (
        payload["approval_evidence_ref"] != evidence_ref
        or payload["resume_token_ref"] != resume_token_ref
        or not _same_lineage(row, shared)
        or any(event[field] != value for field, value in shared.items())
        or event["approval_evidence_ref"] != evidence_ref
        or event["event_id"] != payload["event_id"]
        or event["decision"] != row["evidence_decision"]
    ):
        raise _authority_missing()
    checkpoint_version = row["checkpoint_version"]
    if (
        isinstance(checkpoint_version, bool)
        or not isinstance(checkpoint_version, int)
        or checkpoint_version < 1
    ):
        raise _authority_missing()
    return {
        "schema_version": "ae_nsl_approval_resume_authority.v1",
        "tenant_id": _value(job["tenant_id"]),
        "runtime_job_id": _value(job["runtime_job_id"]),
        "agent_execution_id": _value(row["job_execution_id"]),
        "executable_step_id": _value(row["job_step_id"]),
        "wait_id": payload["wait_id"],
        "event_id": payload["event_id"],
        **shared,
        "approval_evidence_ref": evidence_ref,
        "resume_token_ref": resume_token_ref,
        "checkpoint_version": checkpoint_version,
        "event": event,
    }


def _same_lineage(row: Mapping[str, Any], expected: Mapping[str, str]) -> bool:
    return all(
        _value(row[field]) == expected[target]
        for field, target in (
            ("request_nsl_execution_id", "nsl_execution_id"),
            ("request_business_operation_id", "business_operation_id"),
            ("evidence_nsl_execution_id", "nsl_execution_id"),
            ("evidence_business_operation_id", "business_operation_id"),
            ("inbox_nsl_execution_id", "nsl_execution_id"),
            ("inbox_business_operation_id", "business_operation_id"),
            ("inbox_integrity", "evidence_integrity"),
        )
    )


def _mapping(value: object, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else dict(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise _invalid(f"Stored {label} is malformed.") from exc
    if not isinstance(parsed, dict):
        raise _invalid(f"Stored {label} is malformed.")
    return parsed


def _required(field: str, value: object) -> str:
    text_value = _value(value)
    if not text_value:
        raise _invalid(f"{field} must be a non-empty reference.")
    return text_value


def _value(value: object) -> str:
    return "" if value is None else str(value)


def _invalid(detail: str) -> NslApprovalResumeError:
    return NslApprovalResumeError("ae.nsl_approval_resume_invalid", detail)


def _authority_missing() -> NslApprovalResumeError:
    return NslApprovalResumeError(
        "ae.nsl_approval_resume_authority_missing",
        "NSL approval resume has no exact matched job, wait, event, request, and evidence authority.",
    )


_AUTHORITY_SQL = """
    SELECT job.job_type, job.state AS job_state,
           job.execution_id AS job_execution_id,
           job.executable_step_id AS job_step_id, job.wait_id AS job_wait_id,
           job.lease_owner AS job_lease_owner,
           job.lease_token AS job_lease_token, job.payload_json AS job_payload,
           wait.wait_type, wait.state AS wait_state,
           wait.matched_event_id AS wait_event_id,
           wait.resume_runtime_job_id AS wait_runtime_job_id,
           wait.external_ref AS wait_external_ref,
           wait.approval_request_id AS wait_request_id,
           wait.result_contract_ref AS wait_result_contract_ref,
           wait.agent_execution_id AS wait_execution_id,
           wait.executable_step_id AS wait_step_id,
           wait.nsl_execution_id AS wait_nsl_execution_id,
           wait.business_operation_id AS wait_business_operation_id,
           wait.checkpoint_version,
           step.executor_kind AS step_executor_kind, step.state AS step_state,
           inbox.event_id AS inbox_event_id, inbox.event_type AS inbox_type,
           inbox.state AS inbox_state, inbox.event_payload,
           inbox.approval_request_id AS inbox_request_id,
           inbox.approval_work_item_ref AS inbox_work_item_ref,
           inbox.approval_evidence_ref AS inbox_evidence_ref,
           inbox.evidence_integrity AS inbox_integrity,
           inbox.nsl_execution_id AS inbox_nsl_execution_id,
           inbox.business_operation_id AS inbox_business_operation_id,
           request.approval_request_id AS request_id,
           request.nsl_execution_id AS request_nsl_execution_id,
           request.business_operation_id AS request_business_operation_id,
           evidence.approval_request_id AS evidence_request_id,
           evidence.approval_work_item_ref AS evidence_work_item_ref,
           evidence.nsl_execution_id AS evidence_nsl_execution_id,
           evidence.business_operation_id AS evidence_business_operation_id,
           evidence.evidence_integrity, evidence.decision AS evidence_decision
    FROM ae_runtime_job AS job
    JOIN ae_wait_registration AS wait
      ON wait.tenant_id = job.tenant_id
     AND CAST(wait.wait_id AS TEXT) = job.wait_id
    JOIN ae_external_event_inbox AS inbox
      ON inbox.tenant_id = wait.tenant_id
     AND inbox.event_id = wait.matched_event_id
    JOIN ae_executable_step AS step
      ON step.tenant_id = wait.tenant_id
     AND step.executable_step_id = wait.executable_step_id
    JOIN ae_nsl_approval_request AS request
      ON request.tenant_id = wait.tenant_id
     AND request.approval_request_id = wait.approval_request_id
    JOIN ae_approval_evidence AS evidence
      ON evidence.tenant_id = wait.tenant_id
     AND evidence.approval_request_id = wait.approval_request_id
    WHERE job.tenant_id = :tenant_id AND job.runtime_job_id = :runtime_job_id
"""
