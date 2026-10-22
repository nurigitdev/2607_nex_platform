from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from nex_ae_api import nsl_approval_events as event_module
from nex_ae_api.nsl_approval_events import (
    NSL_APPROVAL_EVENT_SCHEMA_VERSION,
    NslApprovalEventError,
    SqlAlchemyNslApprovalEventService,
    deterministic_nsl_approval_resume_job_id,
    validate_nsl_approval_event,
)
from nex_ae_api.runtime_jobs import RuntimeJobError, SqlAlchemyRuntimeJobQueue
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
NOW_DT = datetime(2026, 10, 22, 14, 0, tzinfo=UTC)
NOW = "2026-10-22T14:00:00Z"
TENANT = "tenant-p8-s50"
EXECUTION_ID = "11111111-1111-4111-8111-111111111150"
STEP_ID = "22222222-2222-4222-8222-222222222250"
WAIT_ID = "33333333-3333-4333-8333-333333333350"
EVENT_ID = "44444444-4444-4444-8444-444444444450"
WORK_ITEM_ID = "55555555-5555-4555-8555-555555555550"
REQUEST_ID = "approval-request-p8-s50"
NSL_EXECUTION_ID = "nsl-execution-p8-s50"
BUSINESS_OPERATION_ID = "business-operation-p8-s50"
INTEGRITY = "sha256:" + "a" * 64


def _event(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": NSL_APPROVAL_EVENT_SCHEMA_VERSION,
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
        "correlation_id": "correlation-p8-s50",
        "causation_id": "decision-p8-s50",
        "occurred_at": NOW,
    }
    value.update(changes)
    return value


def _sessions(
    *,
    parent_state: str = "WAITING_APPROVAL",
    step_state: str = "WAITING",
    executor_kind: str = "LOCAL_SKILL",
    include_wait: bool = True,
    include_evidence: bool = True,
):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_agent_execution (
                    tenant_id TEXT NOT NULL, agent_execution_id TEXT NOT NULL,
                    state TEXT NOT NULL, PRIMARY KEY (tenant_id, agent_execution_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_executable_step (
                    tenant_id TEXT NOT NULL, executable_step_id TEXT NOT NULL,
                    state TEXT NOT NULL, executor_kind TEXT,
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
                    wait_type TEXT NOT NULL, external_ref TEXT NOT NULL,
                    result_contract_ref TEXT NOT NULL, state TEXT NOT NULL,
                    version INTEGER NOT NULL, created_at TEXT NOT NULL,
                    satisfied_at TEXT, updated_at TEXT, matched_event_id TEXT,
                    resume_runtime_job_id TEXT, approval_request_id TEXT,
                    nsl_execution_id TEXT, business_operation_id TEXT,
                    checkpoint_version INTEGER,
                    PRIMARY KEY (tenant_id, wait_id)
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
                    evidence_integrity TEXT NOT NULL, decision TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, approval_request_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_external_event_inbox (
                    tenant_id TEXT NOT NULL, event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL, event_semantic_hash TEXT NOT NULL,
                    external_ref TEXT NOT NULL, result_id TEXT,
                    result_contract_ref TEXT, event_payload TEXT NOT NULL,
                    state TEXT NOT NULL, rejection_reason TEXT,
                    received_at TEXT NOT NULL, processed_at TEXT,
                    approval_request_id TEXT, approval_work_item_ref TEXT,
                    approval_evidence_ref TEXT, evidence_integrity TEXT,
                    nsl_execution_id TEXT, business_operation_id TEXT,
                    PRIMARY KEY (tenant_id, event_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_runtime_job (
                    tenant_id TEXT NOT NULL, runtime_job_id TEXT NOT NULL,
                    job_type TEXT NOT NULL, execution_id TEXT NOT NULL,
                    executable_step_id TEXT, wait_id TEXT, reconciliation_id TEXT,
                    result_delivery_id TEXT, publication_reconciliation_id TEXT,
                    state TEXT NOT NULL, dedup_key TEXT NOT NULL,
                    attempt_no INTEGER NOT NULL, run_after TEXT NOT NULL,
                    lease_owner TEXT, lease_token TEXT, lease_until TEXT,
                    payload_json TEXT NOT NULL, correlation_id TEXT NOT NULL,
                    causation_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, runtime_job_id),
                    UNIQUE (tenant_id, dedup_key)
                )
                """
            )
        )
        connection.execute(
            text("INSERT INTO ae_agent_execution VALUES (:t, :e, :s)"),
            {"t": TENANT, "e": EXECUTION_ID, "s": parent_state},
        )
        connection.execute(
            text("INSERT INTO ae_executable_step VALUES (:t, :s, :state, :kind)"),
            {"t": TENANT, "s": STEP_ID, "state": step_state, "kind": executor_kind},
        )
        if include_wait:
            _insert_wait(connection)
        if include_evidence:
            _insert_evidence(connection)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _insert_wait(connection) -> None:
    connection.execute(
        text(
            """
            INSERT INTO ae_wait_registration (
                tenant_id, wait_id, agent_execution_id, executable_step_id,
                wait_type, external_ref, result_contract_ref, state, version,
                created_at, updated_at, approval_request_id, nsl_execution_id,
                business_operation_id, checkpoint_version
            ) VALUES (
                :tenant, :wait, :execution, :step, 'NSL_APPROVAL', :request,
                'urn:nex:approval-resume:p8:v1', 'PENDING', 1, :now, :now,
                :request, :nsl_execution, :business_operation, 7
            )
            """
        ),
        {
            "tenant": TENANT,
            "wait": WAIT_ID,
            "execution": EXECUTION_ID,
            "step": STEP_ID,
            "request": REQUEST_ID,
            "now": NOW,
            "nsl_execution": NSL_EXECUTION_ID,
            "business_operation": BUSINESS_OPERATION_ID,
        },
    )


def _insert_evidence(connection) -> None:
    connection.execute(
        text(
            "INSERT INTO ae_approval_evidence VALUES "
            "(:tenant, :request, :work_item, :integrity, 'APPROVE')"
        ),
        {
            "tenant": TENANT,
            "request": REQUEST_ID,
            "work_item": WORK_ITEM_ID,
            "integrity": INTEGRITY,
        },
    )


def _service(sessions) -> SqlAlchemyNslApprovalEventService:
    return SqlAlchemyNslApprovalEventService(
        sessions,
        runtime_jobs=SqlAlchemyRuntimeJobQueue(sessions),
        clock=lambda: NOW_DT,
    )


def test_typed_event_matches_exact_wait_and_schedules_ref_only_resume_once() -> None:
    engine, sessions = _sessions()
    service = _service(sessions)

    first = service.ingest(_event())
    replay = service.ingest(_event())

    expected_job_id = deterministic_nsl_approval_resume_job_id(
        tenant_id=TENANT, wait_id=WAIT_ID, event_id=EVENT_ID
    )
    assert first == {
        "schema_version": "ae_nsl_approval_event_acceptance.v1",
        "created": True,
        "event_id": EVENT_ID,
        "inbox_state": "MATCHED",
        "wait_state": "RESUME_QUEUED",
        "resume_runtime_job_id": expected_job_id,
        "rejection_reason": None,
    }
    assert replay == {**first, "created": False}
    with engine.connect() as connection:
        inbox = connection.execute(
            text("SELECT result_id, result_contract_ref FROM ae_external_event_inbox")
        ).one()
        job = connection.execute(
            text("SELECT job_type, payload_json FROM ae_runtime_job")
        ).one()
    assert tuple(inbox) == (None, None)
    assert job[0] == "RESUME_EXECUTION"
    assert set(json.loads(job[1])) == {
        "wait_id",
        "event_id",
        "approval_request_id",
        "approval_work_item_ref",
        "approval_evidence_ref",
        "resume_token_ref",
    }


def test_event_first_converges_after_wait_and_evidence_arrive() -> None:
    engine, sessions = _sessions(include_wait=False, include_evidence=False)
    service = _service(sessions)

    received = service.ingest(_event())
    assert received["inbox_state"] == "RECEIVED"
    with engine.begin() as connection:
        _insert_wait(connection)
    assert service.reconcile_pending()[0]["inbox_state"] == "RECEIVED"
    with engine.begin() as connection:
        _insert_evidence(connection)
    assert service.reconcile_pending()[0]["inbox_state"] == "MATCHED"
    assert service.reconcile_pending() == []


@pytest.mark.parametrize(
    ("event_changes", "reason"),
    (
        ({"decision": "REJECT"}, "APPROVAL_EVIDENCE_LINEAGE_MISMATCH"),
        ({"approval_evidence_ref": "other-ref"}, "APPROVAL_EVIDENCE_REF_MISMATCH"),
    ),
)
def test_changed_evidence_lineage_is_rejected(
    event_changes: dict[str, object], reason: str
) -> None:
    _, sessions = _sessions()
    result = _service(sessions).ingest(_event(**event_changes))

    assert result["inbox_state"] == "REJECTED"
    assert result["rejection_reason"] == reason
    assert result["wait_state"] == "PENDING"


def test_terminal_parent_cancels_wait_and_non_ready_parent_remains_received() -> None:
    _, cancelled_sessions = _sessions(parent_state="CANCELLED")
    cancelled = _service(cancelled_sessions).ingest(_event())
    assert cancelled["rejection_reason"] == "PARENT_CANCELLED"
    assert cancelled["wait_state"] == "CANCELLED"

    _, running_sessions = _sessions(parent_state="RUNNING")
    running = _service(running_sessions).ingest(_event())
    assert running["inbox_state"] == "RECEIVED"
    assert running["wait_state"] == "PENDING"


@pytest.mark.parametrize(
    ("column", "value", "reason"),
    (
        ("state", "CANCELLED", "WAIT_CANCELLED"),
        ("step", "FAILED", "STEP_FAILED"),
    ),
)
def test_terminal_wait_or_step_is_rejected(
    column: str, value: str, reason: str
) -> None:
    engine, sessions = _sessions()
    with engine.begin() as connection:
        if column == "state":
            connection.execute(
                text("UPDATE ae_wait_registration SET state = :value"),
                {"value": value},
            )
        else:
            connection.execute(
                text("UPDATE ae_executable_step SET state = :value"),
                {"value": value},
            )

    result = _service(sessions).ingest(_event())
    assert result["rejection_reason"] == reason


def test_resume_contract_drift_is_rejected() -> None:
    engine, sessions = _sessions()
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_wait_registration SET result_contract_ref = 'other'")
        )

    result = _service(sessions).ingest(_event())
    assert result["rejection_reason"] == "RESUME_CONTRACT_MISMATCH"


def test_event_identity_reuse_with_changed_semantics_conflicts() -> None:
    _, sessions = _sessions(include_wait=False)
    service = _service(sessions)
    service.ingest(_event())

    with pytest.raises(NslApprovalEventError) as conflict:
        service.ingest(_event(correlation_id="different"))
    assert conflict.value.error_code == "ae.nsl_approval_event_idempotency_conflict"


@pytest.mark.parametrize(
    "changes",
    (
        {"schema_version": "other"},
        {"event_name": "WORK_RESULT_SUBMITTED"},
        {"event_id": "bad"},
        {"approval_work_item_ref": "bad"},
        {"tenant_id": ""},
        {"decision": "PENDING"},
        {"evidence_integrity": "bad"},
        {"occurred_at": "bad"},
        {"occurred_at": "2026-10-22T14:00:00"},
    ),
)
def test_typed_event_contract_rejects_malformed_values(changes: dict[str, object]) -> None:
    with pytest.raises(NslApprovalEventError):
        validate_nsl_approval_event(_event(**changes))

    with pytest.raises(NslApprovalEventError):
        validate_nsl_approval_event({**_event(), "extra": True})


def test_reconcile_limit_and_store_failure_fail_closed() -> None:
    engine, sessions = _sessions()
    service = _service(sessions)
    with pytest.raises(NslApprovalEventError):
        service.reconcile_pending(limit=0)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE ae_external_event_inbox"))
    with pytest.raises(NslApprovalEventError) as unavailable:
        service.ingest(_event())
    assert unavailable.value.retryable is True
    with pytest.raises(NslApprovalEventError) as reconcile_unavailable:
        service.reconcile_pending()
    assert reconcile_unavailable.value.retryable is True


def test_runtime_queue_failure_and_wait_race_fail_closed() -> None:
    _, sessions = _sessions()

    class FailingQueue:
        def enqueue_resume_in_session(self, *_args, **_kwargs):
            raise RuntimeJobError("queue.failed", "queue failed", True)

    service = SqlAlchemyNslApprovalEventService(
        sessions, runtime_jobs=FailingQueue(), clock=lambda: NOW_DT  # type: ignore[arg-type]
    )
    with pytest.raises(NslApprovalEventError) as queue_error:
        service.ingest(_event())
    assert queue_error.value.error_code == "queue.failed"
    assert queue_error.value.status_code == 503

    engine, race_sessions = _sessions()

    class RaceQueue:
        def enqueue_resume_in_session(self, session, **values):
            session.execute(text("UPDATE ae_wait_registration SET state = 'CANCELLED'"))
            return {"runtime_job_id": values["runtime_job_id"]}

    race = SqlAlchemyNslApprovalEventService(
        race_sessions, runtime_jobs=RaceQueue(), clock=lambda: NOW_DT  # type: ignore[arg-type]
    )
    with pytest.raises(NslApprovalEventError) as conflict:
        race.ingest(_event())
    assert conflict.value.error_code == "ae.nsl_approval_wait_conflict"
    engine.dispose()


def test_internal_missing_projection_and_malformed_stored_payload_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, sessions = _sessions()
    service = _service(sessions)
    monkeypatch.setattr(event_module, "_load_inbox", lambda *_args, **_kwargs: None)
    with pytest.raises(NslApprovalEventError) as missing:
        service.ingest(_event())
    assert missing.value.status_code == 404

    with pytest.raises(NslApprovalEventError):
        event_module._projection(None, created=False)
    with pytest.raises(NslApprovalEventError):
        event_module._payload([])


def test_s50_migration_adds_typed_columns_without_fake_result_fields() -> None:
    migration = (
        ROOT
        / "database/nex-ae-api/migrations/2505_ae_nsl_approval_event_inbox.sql"
    ).read_text(encoding="utf-8")
    compact = " ".join(migration.lower().split())

    assert "alter column result_id drop not null" in compact
    assert "event_type in ('work_result_submitted', 'nsl_approval_decided')" in compact
    for column in (
        "approval_request_id text null",
        "approval_work_item_ref text null",
        "approval_evidence_ref text null",
        "evidence_integrity text null",
        "nsl_execution_id text null",
        "business_operation_id text null",
    ):
        assert column in compact
    assert "event_type = 'nsl_approval_decided' and result_id is null" in compact
    assert "'2505_ae_nsl_approval_event_inbox'" in compact
    assert "create table" not in compact


def test_error_string_is_safe_detail() -> None:
    assert str(NslApprovalEventError("code", "safe")) == "safe"
