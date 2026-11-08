from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from p8_reliability_faults import (
    WorkerCrashAfterWriteRequestedFaultError,
    WorkerCrashAfterWriteRequestedFaultPort,
    WorkerRestartAfterWriteRequestedRecovery,
)

HASH = "sha256:" + "a" * 64
KEY = "idem:sha256:" + "b" * 64


@dataclass(frozen=True)
class _Precondition:
    evidence_id: str = "precondition-p8-s83"


@dataclass(frozen=True)
class _WriteCallRequest:
    tenant_id: str = "tenant-p8-s83"
    execution_id: str = "nsl-execution-p8-s83"
    business_operation_id: str = "business-operation-p8-s83"
    invocation_id: str = "invocation-p8-s83"
    node_id: str = "write-voucher-draft"
    tool_id: str = "FINANCE.CREATE_VOUCHER_DRAFT"
    contract_hash: str = HASH
    approval_request_id: str = "approval-request-p8-s83"
    idempotency_key: str = KEY
    payload_hash: str = "sha256:" + "c" * 64
    write_intent_hash: str = "sha256:" + "d" * 64
    business_preconditions: _Precondition = _Precondition()


class _Identity:
    @staticmethod
    def from_request(request: object) -> tuple[str, str, str]:
        assert isinstance(request, _WriteCallRequest)
        return (
            request.business_operation_id,
            request.idempotency_key,
            request.payload_hash,
        )


class _Outcome:
    state = "UNKNOWN_COMMIT_STATE"

    def __init__(self, **values: object) -> None:
        self.commit_state = SimpleNamespace(value=self.state)
        self.values = values


class _Committed(_Outcome):
    state = "COMMITTED"


class _NotCommitted(_Outcome):
    state = "NOT_COMMITTED"


class _Unknown(_Outcome):
    pass


class _PublicApi:
    write_call_request = _WriteCallRequest
    write_outcome_identity = _Identity
    write_committed = _Committed
    write_not_committed = _NotCommitted
    write_commit_unknown = _Unknown


class _WriteDelegate:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls = 0

    async def execute(self, request: object) -> object:
        assert isinstance(request, _WriteCallRequest)
        self.calls += 1
        return self.outcome


class _Reconciliation:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls = 0
        self.unknown = None

    async def reconcile(self, request: object, unknown: object) -> object:
        assert isinstance(request, _WriteCallRequest)
        assert isinstance(unknown, _Unknown)
        self.calls += 1
        self.unknown = unknown
        return self.outcome


def _saved(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "tenant_id": "tenant-p8-s83",
        "nsl_execution_id": "nsl-execution-p8-s83",
        "business_operation_id": "business-operation-p8-s83",
        "invocation_id": "invocation-p8-s83",
        "write_node_id": "write-voucher-draft",
        "tool_id": "FINANCE.CREATE_VOUCHER_DRAFT",
        "contract_hash": HASH,
        "approval_request_id": "approval-request-p8-s83",
        "idempotency_key": KEY,
        "payload_hash": "sha256:" + "c" * 64,
        "write_intent_hash": "sha256:" + "d" * 64,
        "precondition_evidence_id": "precondition-p8-s83",
        "record_hash": "sha256:" + "e" * 64,
    }
    value.update(changes)
    return value


def test_fault_discards_one_committed_outcome_after_durable_write_requested() -> None:
    delegate = _WriteDelegate(_Committed())
    port = WorkerCrashAfterWriteRequestedFaultPort(
        delegate,
        lambda _request: _saved(),
        _PublicApi(),
    )

    with pytest.raises(WorkerCrashAfterWriteRequestedFaultError, match="crashed"):
        asyncio.run(port.execute(_WriteCallRequest()))

    assert delegate.calls == 1
    assert port.evidence.provider_dispatches == 1
    assert port.evidence.injected_crashes == 1
    assert port.evidence.response_discarded is True
    assert port.evidence.provider_commit_state == "COMMITTED"
    assert port.evidence.write_request_hash.startswith("sha256:")
    assert port.evidence.write_evidence_record_hash == "sha256:" + "e" * 64
    assert port.evidence.business_operation_id == "business-operation-p8-s83"
    assert port.evidence.idempotency_key == KEY
    assert port.evidence.payload_hash == "sha256:" + "c" * 64

    with pytest.raises(WorkerCrashAfterWriteRequestedFaultError, match="blind"):
        asyncio.run(port.execute(_WriteCallRequest()))
    assert delegate.calls == 1


@pytest.mark.parametrize(
    ("saved", "message"),
    (
        (None, "unavailable"),
        (_saved(payload_hash="sha256:" + "f" * 64), "differs"),
        (_saved(record_hash="invalid"), "record hash"),
    ),
)
def test_fault_fails_closed_before_provider_dispatch(saved, message: str) -> None:
    delegate = _WriteDelegate(_Committed())
    port = WorkerCrashAfterWriteRequestedFaultPort(
        delegate,
        lambda _request: saved,
        _PublicApi(),
    )

    with pytest.raises(WorkerCrashAfterWriteRequestedFaultError, match=message):
        asyncio.run(port.execute(_WriteCallRequest()))
    with pytest.raises(WorkerCrashAfterWriteRequestedFaultError, match="unavailable"):
        _ = port.evidence
    assert delegate.calls == 0


def test_fault_rejects_invalid_request_and_invalid_outcome() -> None:
    port = WorkerCrashAfterWriteRequestedFaultPort(
        _WriteDelegate(_Committed()),
        lambda _request: _saved(),
        _PublicApi(),
    )
    with pytest.raises(WorkerCrashAfterWriteRequestedFaultError, match="admitted"):
        asyncio.run(port.execute(object()))

    invalid = WorkerCrashAfterWriteRequestedFaultPort(
        _WriteDelegate(SimpleNamespace(commit_state=SimpleNamespace(value="LOST"))),
        lambda _request: _saved(),
        _PublicApi(),
    )
    with pytest.raises(WorkerCrashAfterWriteRequestedFaultError, match="commit state"):
        asyncio.run(invalid.execute(_WriteCallRequest()))


@pytest.mark.parametrize("outcome_type", (_Committed, _NotCommitted, _Unknown))
def test_restart_uses_one_authoritative_reconciliation_without_live_write(
    outcome_type,
) -> None:
    reconciliation = _Reconciliation(outcome_type())
    recovery = WorkerRestartAfterWriteRequestedRecovery(
        reconciliation,
        lambda _request: _saved(),
        _PublicApi(),
    )

    result = asyncio.run(recovery.recover(_WriteCallRequest()))

    assert isinstance(result, outcome_type)
    assert reconciliation.calls == 1
    assert reconciliation.unknown.values["reason_code"] == (
        "WORKER_CRASH_AFTER_WRITE_REQUESTED"
    )
    assert reconciliation.unknown.values["evidence_refs"] == (
        "ae.write_requested:" + "sha256:" + "e" * 64,
    )
    assert recovery.evidence.evidence_loads == 1
    assert recovery.evidence.reconciliation_attempts == 1
    assert recovery.evidence.live_write_dispatches == 0
    assert recovery.evidence.assumed_not_committed is False
    assert recovery.evidence.reconciled_commit_state == outcome_type.state
    assert recovery.evidence.write_evidence_record_hash == "sha256:" + "e" * 64

    with pytest.raises(WorkerCrashAfterWriteRequestedFaultError, match="one-shot"):
        asyncio.run(recovery.recover(_WriteCallRequest()))
    assert reconciliation.calls == 1


def test_restart_evidence_is_empty_before_reconciliation() -> None:
    recovery = WorkerRestartAfterWriteRequestedRecovery(
        _Reconciliation(_Committed()),
        lambda _request: _saved(),
        _PublicApi(),
    )

    assert recovery.evidence.evidence_loads == 0
    assert recovery.evidence.reconciliation_attempts == 0
    assert recovery.evidence.reconciled_commit_state is None
    assert recovery.evidence.write_request_hash is None


def test_restart_rejects_invalid_reconciliation_outcome() -> None:
    recovery = WorkerRestartAfterWriteRequestedRecovery(
        _Reconciliation(object()),
        lambda _request: _saved(),
        _PublicApi(),
    )

    with pytest.raises(WorkerCrashAfterWriteRequestedFaultError, match="invalid"):
        asyncio.run(recovery.recover(_WriteCallRequest()))
    assert recovery.evidence.live_write_dispatches == 0


def test_fault_and_recovery_validate_dependencies_and_public_api() -> None:
    api = _PublicApi()
    with pytest.raises(TypeError, match=r"execute\(\)"):
        WorkerCrashAfterWriteRequestedFaultPort(object(), dict, api)
    with pytest.raises(TypeError, match="loader"):
        WorkerCrashAfterWriteRequestedFaultPort(
            _WriteDelegate(_Committed()), None, api  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match=r"reconcile\(\)"):
        WorkerRestartAfterWriteRequestedRecovery(object(), dict, api)
    with pytest.raises(TypeError, match="loader"):
        WorkerRestartAfterWriteRequestedRecovery(
            _Reconciliation(_Committed()), None, api  # type: ignore[arg-type]
        )

    for mutation, message in (
        (("write_outcome_identity", object()), "identity"),
        (("write_commit_unknown", None), "unknown"),
        (("write_call_request", None), "write_call_request"),
        (("write_committed", None), "write_committed"),
        (("write_not_committed", None), "write_not_committed"),
    ):
        invalid_api = _PublicApi()
        setattr(invalid_api, *mutation)
        with pytest.raises(TypeError, match=message):
            WorkerCrashAfterWriteRequestedFaultPort(
                _WriteDelegate(_Committed()), dict, invalid_api
            )
