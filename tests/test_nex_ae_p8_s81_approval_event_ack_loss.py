from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from p8_reliability_faults import (
    ApprovalEventAckLossFaultClient,
    ApprovalEventAckLossFaultError,
)
from run_p8_s81_approval_event_ack_loss import (
    SMOKE_ENV,
    run_p8_s81_approval_event_ack_loss,
    summary_line,
)
from sqlalchemy import text
from test_nex_ae_p8_s50_nsl_approval_event_inbox import (
    EVENT_ID,
    INTEGRITY,
    REQUEST_ID,
    WORK_ITEM_ID,
    _event,
    _service,
    _sessions,
)


class _AdmissionClient:
    def __init__(self, service) -> None:
        self._service = service
        self.calls = 0

    def deliver(self, event):
        self.calls += 1
        return self._service.ingest(event)


class _ResponseClient:
    def __init__(self, response) -> None:
        self.response = response
        self.calls = 0

    def deliver(self, _event):
        self.calls += 1
        return self.response


def test_ack_loss_replay_creates_one_resume_job_and_preserves_binding() -> None:
    engine, sessions = _sessions()
    delegate = _AdmissionClient(_service(sessions))
    fault = ApprovalEventAckLossFaultClient(delegate)

    with pytest.raises(TimeoutError, match="acknowledgement was discarded"):
        fault.deliver(_event())
    acknowledged = fault.deliver(_event())

    assert acknowledged["created"] is False
    assert acknowledged["event_id"] == EVENT_ID
    assert acknowledged["inbox_state"] == "MATCHED"
    assert fault.evidence.delivery_attempts == 2
    assert fault.evidence.downstream_acceptances == 2
    assert fault.evidence.acknowledged_attempts == 1
    assert fault.evidence.unique_event_count == 1
    assert fault.evidence.unique_resume_job_count == 1
    assert fault.evidence.approval_binding_hash.startswith("sha256:")
    with engine.connect() as connection:
        counts = connection.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM ae_external_event_inbox), "
                "(SELECT count(*) FROM ae_runtime_job), "
                "(SELECT count(*) FROM ae_wait_registration "
                " WHERE state = 'RESUME_QUEUED')"
            )
        ).one()
        payload = connection.execute(
            text("SELECT event_payload FROM ae_external_event_inbox")
        ).scalar_one()
    assert tuple(counts) == (1, 1, 1)
    assert REQUEST_ID in payload
    assert WORK_ITEM_ID in payload
    assert INTEGRITY in payload
    assert delegate.calls == 2


def test_retry_semantic_drift_fails_before_second_admission() -> None:
    engine, sessions = _sessions()
    delegate = _AdmissionClient(_service(sessions))
    fault = ApprovalEventAckLossFaultClient(delegate)
    with pytest.raises(TimeoutError):
        fault.deliver(_event())

    changed = deepcopy(_event())
    changed["correlation_id"] = "changed-after-ack-loss"
    with pytest.raises(ApprovalEventAckLossFaultError, match="changed"):
        fault.deliver(changed)

    assert delegate.calls == 1
    assert fault.evidence.delivery_attempts == 2
    assert fault.evidence.downstream_acceptances == 1
    with engine.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM ae_runtime_job")
        ).scalar_one()
    assert count == 1


@pytest.mark.parametrize(
    ("event", "message"),
    (
        (None, "must be an object"),
        ({}, "identity is incomplete"),
        ({**_event(), "approval_request_id": ""}, "identity is incomplete"),
    ),
)
def test_fault_client_rejects_invalid_event_before_delivery(event, message) -> None:
    delegate = _ResponseClient({})
    fault = ApprovalEventAckLossFaultClient(delegate)

    with pytest.raises(ApprovalEventAckLossFaultError, match=message):
        fault.deliver(event)

    assert delegate.calls == 0


@pytest.mark.parametrize(
    "response",
    (
        None,
        {},
        {
            "event_id": "different",
            "inbox_state": "MATCHED",
            "wait_state": "RESUME_QUEUED",
            "resume_runtime_job_id": "job-p8-s81",
        },
        {
            "event_id": EVENT_ID,
            "inbox_state": "REJECTED",
            "wait_state": "PENDING",
            "resume_runtime_job_id": None,
        },
    ),
)
def test_fault_client_requires_durable_exact_acknowledgement(response) -> None:
    fault = ApprovalEventAckLossFaultClient(_ResponseClient(response))

    with pytest.raises(ApprovalEventAckLossFaultError, match="acknowledgement"):
        fault.deliver(_event())

    assert fault.evidence.downstream_acceptances == 0


def test_fault_client_requires_delivery_contract() -> None:
    with pytest.raises(TypeError, match=r"deliver\(\)"):
        ApprovalEventAckLossFaultClient(object())


def test_s81_runner_is_protected_and_has_compact_summary(tmp_path: Path) -> None:
    result = run_p8_s81_approval_event_ack_loss(
        {SMOKE_ENV: "0"},
        execute=False,
        report_path=tmp_path / "report.json",
    )

    assert result["status"] == "SKIPPED"
    assert result["actual_postgres"] is False
    assert summary_line(result).startswith("p8_s81_approval_event_ack_loss=skipped")
