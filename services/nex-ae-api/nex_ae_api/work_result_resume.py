from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.runtime_jobs import RuntimeJobClaim
from nex_ae_api.work_result_events import validate_work_result_event


@dataclass(frozen=True)
class WorkResultResumeError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class SqlAlchemyWorkResultResumeSource:
    """Resolve only the durable event authorized by one RESUME_EXECUTION job."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def resolve(self, claim: RuntimeJobClaim) -> Mapping[str, Any]:
        if not isinstance(claim, RuntimeJobClaim):
            raise _invalid("WorkResult resume requires a RuntimeJobClaim.")
        job = claim.job
        payload = job.get("payload")
        if (
            job.get("job_type") != "RESUME_EXECUTION"
            or job.get("state") != "RUNNING"
            or not isinstance(payload, Mapping)
            or set(payload) != {"wait_id", "event_id", "result_id", "external_ref"}
            or str(job.get("wait_id")) != str(payload.get("wait_id"))
        ):
            raise _invalid("RuntimeJob lacks exact WorkResult resume references.")
        try:
            with self._session_factory() as session:
                row = session.execute(
                    text(
                        "SELECT inbox.event_payload FROM ae_external_event_inbox AS inbox "
                        "JOIN ae_wait_registration AS wait "
                        "ON wait.tenant_id = inbox.tenant_id "
                        "AND wait.matched_event_id = inbox.event_id "
                        "WHERE inbox.tenant_id = :tenant_id "
                        "AND inbox.event_id = :event_id AND inbox.result_id = :result_id "
                        "AND inbox.external_ref = :external_ref "
                        "AND inbox.state = 'MATCHED' AND wait.wait_id = :wait_id "
                        "AND wait.state = 'RESUME_QUEUED' "
                        "AND wait.resume_runtime_job_id = :runtime_job_id"
                    ),
                    {
                        "tenant_id": job["tenant_id"],
                        "event_id": payload["event_id"],
                        "result_id": payload["result_id"],
                        "external_ref": payload["external_ref"],
                        "wait_id": payload["wait_id"],
                        "runtime_job_id": job["runtime_job_id"],
                    },
                ).mappings().first()
        except SQLAlchemyError as exc:
            raise WorkResultResumeError(
                "ae.work_result_resume_store_unavailable",
                "WorkResult resume persistence is unavailable.",
                True,
            ) from exc
        if row is None:
            raise WorkResultResumeError(
                "ae.work_result_resume_authority_missing",
                "WorkResult resume has no exact matched event and wait authority.",
            )
        value = row["event_payload"]
        event = json.loads(value) if isinstance(value, str) else dict(value)
        return validate_work_result_event(event)


def _invalid(detail: str) -> WorkResultResumeError:
    return WorkResultResumeError("ae.work_result_resume_invalid", detail)
