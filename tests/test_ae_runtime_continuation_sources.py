from __future__ import annotations

from types import SimpleNamespace

import pytest
from nex_ae_api.runtime_continuation_sources import (
    RuntimeContinuationSourceError,
    RuntimeContinuationSourceRegistry,
)
from nex_ae_api.runtime_jobs import RuntimeJobClaim


class _Source:
    def __init__(self, value: str) -> None:
        self.value = value
        self.claims: list[RuntimeJobClaim] = []

    def resolve(self, claim: RuntimeJobClaim):
        self.claims.append(claim)
        return {"source": self.value}


def _claim(payload: dict[str, str]) -> RuntimeJobClaim:
    return RuntimeJobClaim(
        job={
            "job_type": "RESUME_EXECUTION",
            "payload": payload,
        },
        attempt={},
    )


def test_registry_routes_exact_payload_contract_without_business_values() -> None:
    approval = _Source("approval")
    work_result = _Source("work-result")
    registry = RuntimeContinuationSourceRegistry(
        {
            frozenset({"wait_id", "approval_request_id"}): approval,
            frozenset({"wait_id", "result_id"}): work_result,
        }
    )
    approval_claim = _claim({"wait_id": "wait-a", "approval_request_id": "approval-a"})
    result_claim = _claim({"wait_id": "wait-b", "result_id": "result-b"})

    assert registry.resolve(approval_claim) == {"source": "approval"}
    assert registry.resolve(result_claim) == {"source": "work-result"}
    assert approval.claims == [approval_claim]
    assert work_result.claims == [result_claim]


@pytest.mark.parametrize(
    "claim",
    [
        SimpleNamespace(),
        _claim({"wait_id": "wait", "unknown": "value"}),
    ],
)
def test_registry_fails_closed_for_unadmitted_resume_contract(claim) -> None:
    registry = RuntimeContinuationSourceRegistry(
        {frozenset({"wait_id", "result_id"}): _Source("work-result")}
    )

    with pytest.raises(RuntimeContinuationSourceError):
        registry.resolve(claim)


def test_registry_rejects_empty_or_non_resolving_sources() -> None:
    with pytest.raises(RuntimeContinuationSourceError):
        RuntimeContinuationSourceRegistry({})
    with pytest.raises(RuntimeContinuationSourceError):
        RuntimeContinuationSourceRegistry({frozenset({"wait_id"}): object()})
