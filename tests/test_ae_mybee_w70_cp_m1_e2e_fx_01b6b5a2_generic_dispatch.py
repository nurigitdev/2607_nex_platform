from pathlib import Path

import pytest
from nex_ae_api.agent_runtime_worker import AgentRuntimeAssignment
from nex_ae_api.runtime_assignment_handlers import (
    RuntimeAssignmentHandlerError,
    RuntimeAssignmentHandlerRegistry,
)
from nex_ae_api.runtime_jobs import RuntimeJobClaim

ROOT = Path(__file__).resolve().parents[1]
AE_SOURCE = ROOT / "services/nex-ae-api/nex_ae_api"


def _assignment(kind: str = "EXECUTABLE_STEP") -> AgentRuntimeAssignment:
    return AgentRuntimeAssignment(
        tenant_id="tenant-generic",
        executor_kind="DETERMINISTIC_REPORT",
        backend_profile="NSL_V02_IN_PROCESS",
        assignment_kind=kind,
        claim=RuntimeJobClaim(
            job={
                "tenant_id": "tenant-generic",
                "runtime_job_id": "job-generic",
                "state": "RUNNING",
                "lease_owner": "worker-generic",
                "lease_token": "lease-generic",
            },
            attempt={"attempt_no": 1},
        ),
    )


@pytest.mark.parametrize(
    "handlers",
    (
        {},
        {"UNKNOWN": lambda _assignment: {}},
        {"EXECUTABLE_STEP": object()},
    ),
)
def test_handler_registry_rejects_invalid_registration(handlers) -> None:
    with pytest.raises(RuntimeAssignmentHandlerError):
        RuntimeAssignmentHandlerRegistry(handlers)


def test_handler_registry_rejects_invalid_assignment_and_result() -> None:
    registry = RuntimeAssignmentHandlerRegistry(
        {"EXECUTABLE_STEP": lambda _assignment: "invalid"}
    )
    with pytest.raises(RuntimeAssignmentHandlerError):
        registry("invalid")  # type: ignore[arg-type]
    with pytest.raises(RuntimeAssignmentHandlerError):
        registry(_assignment())


def test_product_assignment_does_not_enter_step_executor_or_scenario_code() -> None:
    step_executors = (AE_SOURCE / "step_executors.py").read_text(encoding="utf-8")
    generic_sources = "\n".join(
        (AE_SOURCE / filename).read_text(encoding="utf-8")
        for filename in (
            "agent_runtime_dispatcher.py",
            "agent_runtime_worker.py",
            "runtime_assignment_handlers.py",
            "runtime_jobs.py",
        )
    ).lower()

    assert "PRODUCT_COORDINATOR" not in step_executors
    assert "m1_" not in generic_sources
    assert "golden" not in generic_sources
    assert "fixture" not in generic_sources
