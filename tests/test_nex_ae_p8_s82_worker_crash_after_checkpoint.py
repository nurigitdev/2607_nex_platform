from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

import pytest
from p8_reliability_faults import (
    WorkerCrashAfterCheckpointFaultError,
    WorkerCrashAfterCheckpointFaultPort,
)
from run_p8_s82_worker_crash_after_checkpoint import (
    SMOKE_ENV,
    run_p8_s82_worker_crash_after_checkpoint,
    summary_line,
)


class _Request:
    def __init__(self, **changes: object) -> None:
        self.value = {
            "execution_id": "nsl-execution-p8-s82",
            "business_operation_id": "business-operation-p8-s82",
            "approval_request_id": "approval-request-p8-s82",
            "skill_semantic_hash": "sha256:" + "a" * 64,
            "payload_hash": "sha256:" + "b" * 64,
            "protected_payload_ref": "snapshot://p8-s82/manifest-bound-payload",
        }
        self.value.update(changes)

    def to_data(self):
        return deepcopy(self.value)


class _Delegate:
    def __init__(self) -> None:
        self.calls = 0
        self.requests = []

    async def publish(self, request):
        self.calls += 1
        self.requests.append(request.to_data())
        return "published"


def _checkpoint(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "execution_id": "nsl-execution-p8-s82",
        "business_operation_id": "business-operation-p8-s82",
        "checkpoint_version": 3,
        "skill_id": "FINANCE.CREATE_VOUCHER_DRAFT",
        "skill_version": "0.2.0",
        "semantic_hash": "sha256:" + "a" * 64,
        "ir_version": "1.1",
        "runtime_version": "0.1.0",
        "state_payload": "c3RhdGU=",
        "integrity_hash": "sha256:" + "c" * 64,
    }
    value.update(changes)
    return value


def test_worker_restart_publishes_exact_checkpoint_request_once() -> None:
    delegate = _Delegate()
    fault = WorkerCrashAfterCheckpointFaultPort(delegate, _checkpoint)

    result = asyncio.run(fault.publish_after_restart(_Request()))

    assert result == "published"
    assert delegate.calls == 1
    assert fault.evidence.publication_attempts == 2
    assert fault.evidence.injected_crashes == 1
    assert fault.evidence.restart_attempts == 1
    assert fault.evidence.downstream_publications == 1
    assert fault.evidence.checkpoint_hash.startswith("sha256:")
    assert fault.evidence.checkpoint_integrity_hash == "sha256:" + "c" * 64
    assert fault.evidence.checkpoint_version == 3
    assert fault.evidence.approval_request_hash.startswith("sha256:")
    assert fault.evidence.approval_request_id == "approval-request-p8-s82"
    assert fault.evidence.payload_hash == "sha256:" + "b" * 64
    assert fault.evidence.protected_payload_ref.startswith("snapshot://")


def test_restart_request_drift_fails_before_downstream_publication() -> None:
    delegate = _Delegate()
    fault = WorkerCrashAfterCheckpointFaultPort(delegate, _checkpoint)

    with pytest.raises(WorkerCrashAfterCheckpointFaultError, match="crashed"):
        asyncio.run(fault.publish(_Request()))
    with pytest.raises(WorkerCrashAfterCheckpointFaultError, match="changed"):
        asyncio.run(fault.publish(_Request(protected_payload_ref="snapshot://changed")))

    assert delegate.calls == 0
    assert fault.evidence.publication_attempts == 2
    assert fault.evidence.restart_attempts == 0


def test_restart_checkpoint_drift_fails_before_downstream_publication() -> None:
    current = _checkpoint()
    delegate = _Delegate()
    fault = WorkerCrashAfterCheckpointFaultPort(delegate, lambda: current)

    with pytest.raises(WorkerCrashAfterCheckpointFaultError):
        asyncio.run(fault.publish(_Request()))
    current["checkpoint_version"] = 4
    with pytest.raises(WorkerCrashAfterCheckpointFaultError, match="changed"):
        asyncio.run(fault.publish(_Request()))

    assert delegate.calls == 0


@pytest.mark.parametrize(
    ("checkpoint", "message"),
    (
        (None, "not an object"),
        ({}, "identity is incomplete"),
        (_checkpoint(checkpoint_version=False), "version is invalid"),
        (_checkpoint(execution_id=""), "identity is incomplete"),
        (_checkpoint(semantic_hash="invalid"), "semantic_hash is invalid"),
        (_checkpoint(integrity_hash="sha256:" + "G" * 64), "integrity_hash is invalid"),
        (_checkpoint(execution_id="different"), "lineage differ"),
    ),
)
def test_invalid_checkpoint_fails_before_crash_or_publication(
    checkpoint, message
) -> None:
    delegate = _Delegate()
    fault = WorkerCrashAfterCheckpointFaultPort(delegate, lambda: checkpoint)

    with pytest.raises(WorkerCrashAfterCheckpointFaultError, match=message):
        asyncio.run(fault.publish(_Request()))

    assert delegate.calls == 0
    assert fault.evidence.injected_crashes == 0


@pytest.mark.parametrize(
    ("approval_input", "message"),
    (
        (object(), "not canonical"),
        (_Request(approval_request_id=""), "identity is incomplete"),
        (_Request(payload_hash="invalid"), "payload_hash is invalid"),
        (
            _Request(skill_semantic_hash="sha256:" + "G" * 64),
            "skill_semantic_hash is invalid",
        ),
    ),
)
def test_invalid_request_fails_before_crash_or_publication(
    approval_input, message
) -> None:
    delegate = _Delegate()
    fault = WorkerCrashAfterCheckpointFaultPort(delegate, _checkpoint)

    with pytest.raises(WorkerCrashAfterCheckpointFaultError, match=message):
        asyncio.run(fault.publish(approval_input))

    assert delegate.calls == 0
    assert fault.evidence.injected_crashes == 0


def test_fault_port_requires_delegate_and_checkpoint_loader_contracts() -> None:
    with pytest.raises(TypeError, match=r"publish\(\)"):
        WorkerCrashAfterCheckpointFaultPort(object(), _checkpoint)
    with pytest.raises(TypeError, match="loader"):
        WorkerCrashAfterCheckpointFaultPort(_Delegate(), None)  # type: ignore[arg-type]


def test_publish_after_restart_requires_first_attempt_to_crash() -> None:
    class _NoCrash(WorkerCrashAfterCheckpointFaultPort):
        async def publish(self, request):
            return "unexpected"

    fault = _NoCrash(_Delegate(), _checkpoint)

    with pytest.raises(WorkerCrashAfterCheckpointFaultError, match="did not stop"):
        asyncio.run(fault.publish_after_restart(_Request()))


def test_publish_after_restart_propagates_pre_crash_validation_failure() -> None:
    fault = WorkerCrashAfterCheckpointFaultPort(_Delegate(), dict)

    with pytest.raises(
        WorkerCrashAfterCheckpointFaultError, match="identity is incomplete"
    ):
        asyncio.run(fault.publish_after_restart(_Request()))

    assert fault.evidence.injected_crashes == 0


def test_s82_runner_is_protected_and_has_compact_summary(tmp_path: Path) -> None:
    result = run_p8_s82_worker_crash_after_checkpoint(
        {SMOKE_ENV: "0"},
        execute=False,
        report_path=tmp_path / "report.json",
    )

    assert result["status"] == "SKIPPED"
    assert result["actual_postgres"] is False
    assert summary_line(result).startswith(
        "p8_s82_worker_crash_after_checkpoint=skipped"
    )
