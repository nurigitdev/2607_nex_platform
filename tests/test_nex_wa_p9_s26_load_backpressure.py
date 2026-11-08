from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest
from nex_runtime import InMemoryJobQueue, JobQueueError, SqlAlchemyJobQueue
from nex_wa import WaEvidenceIntakeService
from nex_wa.intake_contracts import WaIntakeContractError

NOW = datetime(2026, 10, 28, 8, 0, tzinfo=UTC)


def _payload(source_ref: str = "execution-s26") -> dict[str, str]:
    return {
        "schema_version": "wa_evidence_intake_request.v1",
        "tenant_id": "VO00",
        "source_type": "AE_AGENT_RESULT",
        "source_ref": source_ref,
        "source_revision_ref": f"result-{source_ref}",
        "source_hash": "sha256:" + "a" * 64,
        "occurred_at": "2026-10-28T08:00:00Z",
        "correlation_id": f"corr-{source_ref}",
    }


class ConcurrentWinnerQueue(InMemoryJobQueue):
    def __init__(
        self,
        *,
        winner_visible: bool = True,
        conflicting_winner: bool = False,
        lookup_fails: bool = False,
    ) -> None:
        super().__init__()
        self.winner_visible = winner_visible
        self.conflicting_winner = conflicting_winner
        self.lookup_fails = lookup_fails
        self._initial_lookup = True

    def get_job(self, job_id: str):
        if self._initial_lookup:
            self._initial_lookup = False
            return None
        if not self.winner_visible:
            return None
        if self.lookup_fails:
            raise JobQueueError(
                error_code="job.store_unavailable",
                detail="private lookup detail",
                status_code=503,
            )
        stored = super().get_job(job_id)
        if stored is not None and self.conflicting_winner:
            stored["payload"]["source_hash"] = "sha256:" + "b" * 64
        return stored

    def enqueue(self, job):
        super().enqueue(job)
        raise JobQueueError(
            error_code="job.duplicate_id",
            detail="simulated concurrent winner",
            status_code=409,
        )


def test_concurrent_first_enqueue_recovers_visible_deterministic_winner() -> None:
    service = WaEvidenceIntakeService(
        ConcurrentWinnerQueue(),
        clock=lambda: NOW,
    )

    result = service.admit(
        _payload(),
        caller_service_id="nex-ae-api",
        request_id="request-loser",
        trace_id="trace-loser",
    )

    assert result.status == "QUEUED"
    assert result.idempotent_reuse is True


def test_duplicate_without_durable_winner_remains_retryable_503() -> None:
    service = WaEvidenceIntakeService(
        ConcurrentWinnerQueue(winner_visible=False),
        clock=lambda: NOW,
    )

    with pytest.raises(WaIntakeContractError) as raised:
        service.admit(
            _payload(),
            caller_service_id="nex-ae-api",
            request_id="request-loser",
            trace_id="trace-loser",
        )

    assert raised.value.error_code == "WA_INTAKE_STORE_UNAVAILABLE"
    assert raised.value.status_code == 503


@pytest.mark.parametrize(
    "queue",
    [
        ConcurrentWinnerQueue(lookup_fails=True),
        ConcurrentWinnerQueue(winner_visible=False),
    ],
)
def test_duplicate_recovery_requires_durably_readable_winner(queue) -> None:
    service = WaEvidenceIntakeService(queue, clock=lambda: NOW)
    with pytest.raises(WaIntakeContractError) as raised:
        service.admit(
            _payload(),
            caller_service_id="nex-ae-api",
            request_id="request-loser",
            trace_id="trace-loser",
        )
    assert raised.value.error_code == "WA_INTAKE_STORE_UNAVAILABLE"


def test_concurrent_winner_semantic_conflict_is_not_hidden_as_backpressure() -> None:
    service = WaEvidenceIntakeService(
        ConcurrentWinnerQueue(conflicting_winner=True),
        clock=lambda: NOW,
    )
    with pytest.raises(WaIntakeContractError) as raised:
        service.admit(
            _payload(),
            caller_service_id="nex-ae-api",
            request_id="request-loser",
            trace_id="trace-loser",
        )
    assert raised.value.error_code == "WA_SOURCE_IDEMPOTENCY_CONFLICT"
    assert raised.value.status_code == 409


def test_non_duplicate_store_failure_is_retryable_and_source_neutral() -> None:
    class UnavailableQueue(InMemoryJobQueue):
        def enqueue(self, job):
            raise JobQueueError(
                error_code="job.store_unavailable",
                detail="private database detail",
                status_code=503,
            )

    payload = _payload()
    service = WaEvidenceIntakeService(UnavailableQueue(), clock=lambda: NOW)
    with pytest.raises(WaIntakeContractError) as raised:
        service.admit(
            payload,
            caller_service_id="nex-ae-api",
            request_id="request",
            trace_id="trace",
        )

    assert raised.value.error_code == "WA_INTAKE_STORE_UNAVAILABLE"
    assert raised.value.status_code == 503
    assert "private" not in str(raised.value)
    assert payload == _payload()


def test_postgres_claim_contract_uses_skip_locked() -> None:
    source = inspect.getsource(SqlAlchemyJobQueue._select_claim_candidate)

    assert '"FOR UPDATE SKIP LOCKED"' in source
    assert "LIMIT 1" in source
    assert "ORDER BY available_at, created_at, job_id" in source
