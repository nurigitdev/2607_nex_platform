from __future__ import annotations

import copy
import json

import pytest
from nex_ae_api.nsl_approval_resume import (
    NslApprovalResumeError,
    SqlAlchemyNslApprovalResumeSource,
)
from nex_ae_api.runtime_jobs import RuntimeJobClaim
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT = "tenant-p8-s51"
JOB_ID = "11111111-1111-4111-8111-111111111151"
EXECUTION_ID = "22222222-2222-4222-8222-222222222251"
STEP_ID = "step-p8-s51"
WAIT_ID = "33333333-3333-4333-8333-333333333351"
EVENT_ID = "44444444-4444-4444-8444-444444444451"
WORK_ITEM_ID = "55555555-5555-4555-8555-555555555551"
REQUEST_ID = "approval-request-p8-s51"
NSL_EXECUTION_ID = "nsl-execution-p8-s51"
BUSINESS_OPERATION_ID = "business-operation-p8-s51"
INTEGRITY = "sha256:" + "a" * 64
LEASE_TOKEN = "lease-p8-s51"
WORKER_ID = "worker-p8-s51"


def _event(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "ae_nsl_approval_decided_event.v1",
        "event_id": EVENT_ID,
        "event_name": "NSL_APPROVAL_DECIDED",
        "tenant_id": TENANT,
        "approval_work_item_ref": WORK_ITEM_ID,
        "approval_request_id": REQUEST_ID,
        "nsl_execution_id": NSL_EXECUTION_ID,
        "business_operation_id": BUSINESS_OPERATION_ID,
        "decision": "APPROVE",
        "approval_evidence_ref": f"ae-approval-evidence:{REQUEST_ID}",
        "evidence_integrity": INTEGRITY,
        "correlation_id": "correlation-p8-s51",
        "causation_id": "decision-p8-s51",
        "occurred_at": "2026-10-22T15:00:00Z",
    }
    value.update(changes)
    return value


def _payload(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "wait_id": WAIT_ID,
        "event_id": EVENT_ID,
        "approval_request_id": REQUEST_ID,
        "approval_work_item_ref": WORK_ITEM_ID,
        "approval_evidence_ref": f"ae-approval-evidence:{REQUEST_ID}",
        "resume_token_ref": f"ae-nsl-resume:{INTEGRITY}",
    }
    value.update(changes)
    return value


def _claim(
    *,
    job_changes: dict[str, object] | None = None,
    attempt_changes: dict[str, object] | None = None,
) -> RuntimeJobClaim:
    job: dict[str, object] = {
        "tenant_id": TENANT,
        "runtime_job_id": JOB_ID,
        "job_type": "RESUME_EXECUTION",
        "execution_id": EXECUTION_ID,
        "executable_step_id": STEP_ID,
        "wait_id": WAIT_ID,
        "state": "RUNNING",
        "lease_owner": WORKER_ID,
        "lease_token": LEASE_TOKEN,
        "payload": _payload(),
    }
    attempt: dict[str, object] = {
        "tenant_id": TENANT,
        "runtime_job_id": JOB_ID,
        "worker_id": WORKER_ID,
        "lease_token": LEASE_TOKEN,
        "outcome": "RUNNING",
    }
    job.update(job_changes or {})
    attempt.update(attempt_changes or {})
    return RuntimeJobClaim(job=job, attempt=attempt)  # type: ignore[arg-type]


def _sessions():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_runtime_job (
                    tenant_id TEXT NOT NULL, runtime_job_id TEXT NOT NULL,
                    job_type TEXT NOT NULL, execution_id TEXT NOT NULL,
                    executable_step_id TEXT, wait_id TEXT, state TEXT NOT NULL,
                    lease_owner TEXT, lease_token TEXT, payload_json TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, runtime_job_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_executable_step (
                    tenant_id TEXT NOT NULL, executable_step_id TEXT NOT NULL,
                    executor_kind TEXT, state TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, executable_step_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_wait_registration (
                    tenant_id TEXT NOT NULL, wait_id TEXT NOT NULL,
                    agent_execution_id TEXT NOT NULL, executable_step_id TEXT NOT NULL,
                    wait_type TEXT NOT NULL, state TEXT NOT NULL,
                    matched_event_id TEXT, resume_runtime_job_id TEXT,
                    external_ref TEXT NOT NULL, approval_request_id TEXT,
                    result_contract_ref TEXT NOT NULL, nsl_execution_id TEXT,
                    business_operation_id TEXT, checkpoint_version INTEGER,
                    PRIMARY KEY (tenant_id, wait_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_external_event_inbox (
                    tenant_id TEXT NOT NULL, event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL, state TEXT NOT NULL,
                    event_payload TEXT NOT NULL, approval_request_id TEXT,
                    approval_work_item_ref TEXT, approval_evidence_ref TEXT,
                    evidence_integrity TEXT, nsl_execution_id TEXT,
                    business_operation_id TEXT,
                    PRIMARY KEY (tenant_id, event_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_nsl_approval_request (
                    tenant_id TEXT NOT NULL, approval_request_id TEXT NOT NULL,
                    nsl_execution_id TEXT NOT NULL,
                    business_operation_id TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, approval_request_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_approval_evidence (
                    tenant_id TEXT NOT NULL, approval_request_id TEXT NOT NULL,
                    approval_work_item_ref TEXT NOT NULL,
                    nsl_execution_id TEXT NOT NULL,
                    business_operation_id TEXT NOT NULL,
                    evidence_integrity TEXT NOT NULL, decision TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, approval_request_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO ae_runtime_job VALUES (
                    :tenant, :job, 'RESUME_EXECUTION', :execution, :step, :wait,
                    'RUNNING', :worker, :lease, :payload
                )
                """
            ),
            {
                "tenant": TENANT,
                "job": JOB_ID,
                "execution": EXECUTION_ID,
                "step": STEP_ID,
                "wait": WAIT_ID,
                "worker": WORKER_ID,
                "lease": LEASE_TOKEN,
                "payload": json.dumps(_payload()),
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO ae_executable_step VALUES (
                    :tenant, :step, 'LOCAL_SKILL', 'WAITING'
                )
                """
            ),
            {"tenant": TENANT, "step": STEP_ID},
        )
        connection.execute(
            text(
                """
                INSERT INTO ae_wait_registration VALUES (
                    :tenant, :wait, :execution, :step, 'NSL_APPROVAL',
                    'RESUME_QUEUED', :event, :job, :request, :request,
                    'urn:nex:approval-resume:p8:v1', :nsl, :business, 7
                )
                """
            ),
            {
                "tenant": TENANT,
                "wait": WAIT_ID,
                "execution": EXECUTION_ID,
                "step": STEP_ID,
                "event": EVENT_ID,
                "job": JOB_ID,
                "request": REQUEST_ID,
                "nsl": NSL_EXECUTION_ID,
                "business": BUSINESS_OPERATION_ID,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO ae_external_event_inbox VALUES (
                    :tenant, :event, 'NSL_APPROVAL_DECIDED', 'MATCHED', :payload,
                    :request, :work_item, :evidence_ref, :integrity, :nsl, :business
                )
                """
            ),
            {
                "tenant": TENANT,
                "event": EVENT_ID,
                "payload": json.dumps(_event()),
                "request": REQUEST_ID,
                "work_item": WORK_ITEM_ID,
                "evidence_ref": f"ae-approval-evidence:{REQUEST_ID}",
                "integrity": INTEGRITY,
                "nsl": NSL_EXECUTION_ID,
                "business": BUSINESS_OPERATION_ID,
            },
        )
        connection.execute(
            text(
                "INSERT INTO ae_nsl_approval_request VALUES "
                "(:tenant, :request, :nsl, :business)"
            ),
            {
                "tenant": TENANT,
                "request": REQUEST_ID,
                "nsl": NSL_EXECUTION_ID,
                "business": BUSINESS_OPERATION_ID,
            },
        )
        connection.execute(
            text(
                "INSERT INTO ae_approval_evidence VALUES "
                "(:tenant, :request, :work_item, :nsl, :business, "
                ":integrity, 'APPROVE')"
            ),
            {
                "tenant": TENANT,
                "request": REQUEST_ID,
                "work_item": WORK_ITEM_ID,
                "nsl": NSL_EXECUTION_ID,
                "business": BUSINESS_OPERATION_ID,
                "integrity": INTEGRITY,
            },
        )
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_resolve_returns_exact_durable_resume_authority() -> None:
    _, sessions = _sessions()

    authority = SqlAlchemyNslApprovalResumeSource(sessions).resolve(_claim())

    assert authority == {
        "schema_version": "ae_nsl_approval_resume_authority.v1",
        "tenant_id": TENANT,
        "runtime_job_id": JOB_ID,
        "agent_execution_id": EXECUTION_ID,
        "executable_step_id": STEP_ID,
        "wait_id": WAIT_ID,
        "event_id": EVENT_ID,
        "approval_request_id": REQUEST_ID,
        "approval_work_item_ref": WORK_ITEM_ID,
        "nsl_execution_id": NSL_EXECUTION_ID,
        "business_operation_id": BUSINESS_OPERATION_ID,
        "evidence_integrity": INTEGRITY,
        "approval_evidence_ref": f"ae-approval-evidence:{REQUEST_ID}",
        "resume_token_ref": f"ae-nsl-resume:{INTEGRITY}",
        "checkpoint_version": 7,
        "event": _event(),
    }


@pytest.mark.parametrize(
    ("job_changes", "attempt_changes"),
    (
        ({"job_type": "CONTINUE_EXECUTION"}, {}),
        ({"state": "QUEUED"}, {}),
        ({"payload": {**_payload(), "extra": "bad"}}, {}),
        ({}, {"outcome": "DONE"}),
        ({"wait_id": "other"}, {}),
        ({}, {"tenant_id": "other"}),
        ({}, {"runtime_job_id": "other"}),
        ({}, {"lease_token": "other"}),
        ({}, {"worker_id": "other"}),
    ),
)
def test_claim_must_be_the_exact_running_attempt(
    job_changes: dict[str, object], attempt_changes: dict[str, object]
) -> None:
    _, sessions = _sessions()

    with pytest.raises(NslApprovalResumeError) as error:
        SqlAlchemyNslApprovalResumeSource(sessions).resolve(
            _claim(job_changes=job_changes, attempt_changes=attempt_changes)
        )
    assert error.value.error_code == "ae.nsl_approval_resume_invalid"


def test_claim_type_and_empty_reference_fail_closed() -> None:
    _, sessions = _sessions()
    source = SqlAlchemyNslApprovalResumeSource(sessions)

    with pytest.raises(NslApprovalResumeError):
        source.resolve(object())  # type: ignore[arg-type]
    with pytest.raises(NslApprovalResumeError):
        source.resolve(_claim(job_changes={"payload": _payload(event_id="")}))


@pytest.mark.parametrize(
    "statement",
    (
        "UPDATE ae_runtime_job SET state = 'QUEUED'",
        "UPDATE ae_runtime_job SET payload_json = '{}'",
        "UPDATE ae_wait_registration SET state = 'PENDING'",
        "UPDATE ae_executable_step SET executor_kind = 'DETERMINISTIC_REPORT'",
        "UPDATE ae_executable_step SET state = 'RUNNING'",
        "UPDATE ae_wait_registration SET matched_event_id = 'other'",
        "UPDATE ae_external_event_inbox SET state = 'RECEIVED'",
        "UPDATE ae_external_event_inbox SET approval_evidence_ref = 'other'",
        "UPDATE ae_nsl_approval_request SET business_operation_id = 'other'",
        "UPDATE ae_approval_evidence SET evidence_integrity = 'sha256:" + "b" * 64 + "'",
        "UPDATE ae_approval_evidence SET decision = 'REJECT'",
    ),
)
def test_persisted_job_wait_event_request_and_evidence_drift_fail_closed(
    statement: str,
) -> None:
    engine, sessions = _sessions()
    with engine.begin() as connection:
        connection.execute(text(statement))

    with pytest.raises(NslApprovalResumeError) as error:
        SqlAlchemyNslApprovalResumeSource(sessions).resolve(_claim())
    assert error.value.error_code == "ae.nsl_approval_resume_authority_missing"


def test_event_lineage_and_checkpoint_drift_fail_closed() -> None:
    engine, sessions = _sessions()
    with engine.begin() as connection:
        changed = copy.deepcopy(_event(nsl_execution_id="other"))
        connection.execute(
            text("UPDATE ae_external_event_inbox SET event_payload = :payload"),
            {"payload": json.dumps(changed)},
        )
    with pytest.raises(NslApprovalResumeError):
        SqlAlchemyNslApprovalResumeSource(sessions).resolve(_claim())

    engine, sessions = _sessions()
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_wait_registration SET checkpoint_version = 0")
        )
    with pytest.raises(NslApprovalResumeError):
        SqlAlchemyNslApprovalResumeSource(sessions).resolve(_claim())


def test_malformed_stored_payloads_and_store_failure_use_typed_errors() -> None:
    engine, sessions = _sessions()
    source = SqlAlchemyNslApprovalResumeSource(sessions)
    with engine.begin() as connection:
        connection.execute(text("UPDATE ae_runtime_job SET payload_json = '[]'"))
    with pytest.raises(NslApprovalResumeError) as malformed:
        source.resolve(_claim())
    assert malformed.value.error_code == "ae.nsl_approval_resume_invalid"

    engine, sessions = _sessions()
    with engine.begin() as connection:
        connection.execute(text("UPDATE ae_runtime_job SET payload_json = '{'"))
    with pytest.raises(NslApprovalResumeError) as invalid_json:
        SqlAlchemyNslApprovalResumeSource(sessions).resolve(_claim())
    assert invalid_json.value.error_code == "ae.nsl_approval_resume_invalid"

    engine, sessions = _sessions()
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_external_event_inbox SET event_payload = '{}'")
        )
    with pytest.raises(NslApprovalResumeError) as bad_event:
        SqlAlchemyNslApprovalResumeSource(sessions).resolve(_claim())
    assert bad_event.value.error_code == "ae.nsl_approval_resume_invalid"

    engine, sessions = _sessions()
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE ae_runtime_job"))
    with pytest.raises(NslApprovalResumeError) as unavailable:
        SqlAlchemyNslApprovalResumeSource(sessions).resolve(_claim())
    assert unavailable.value.retryable is True


def test_missing_authority_and_safe_error_string() -> None:
    engine, sessions = _sessions()
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM ae_approval_evidence"))
    with pytest.raises(NslApprovalResumeError) as missing:
        SqlAlchemyNslApprovalResumeSource(sessions).resolve(_claim())
    assert missing.value.error_code == "ae.nsl_approval_resume_authority_missing"
    assert str(NslApprovalResumeError("code", "safe")) == "safe"
