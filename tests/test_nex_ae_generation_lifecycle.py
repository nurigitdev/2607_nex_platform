from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from nex_ae_api.async_generation import build_async_generation_projection
from nex_ae_api.cx_async_generation_client import CxAsyncGenerationClientError
from nex_ae_api.generation_lifecycle import (
    AE_GENERATION_LIFECYCLE_ORCHESTRATION_SCHEMA_VERSION,
    AeGenerationLifecycleError,
    orchestrate_generation_lifecycle,
)


def _job(status: str = "QUEUED", *, retryable: bool = True) -> dict[str, Any]:
    error = None
    if status in {"FAILED", "CANCELLED"}:
        error = {
            "error_code": "cx.generation.failed",
            "retryable": retryable,
            "dead_lettered": not retryable,
        }
    return {
        "job_id": "job-1044",
        "cx_generation_id": "generation-1044",
        "status": status,
        "attempt_count": 1 if status != "QUEUED" else 0,
        "max_attempts": 3,
        "retryable": retryable,
        "links": {
            "generation": "/api/v1/generations/generation-1044",
            "async_job": "/api/v1/generation-jobs/job-1044",
        },
        "error": error,
    }


def _record(status: str = "QUEUED", *, retryable: bool = True) -> dict[str, Any]:
    projection = build_async_generation_projection(
        {
            "admission_status": "ENQUEUED",
            "job": _job(status, retryable=retryable),
            "generation": None,
        }
    )
    return {
        "interaction_id": "interaction-1044",
        "tenant_id": "tenant-a",
        "owner_user_id": "user-a",
        "generation": {"async_generation": projection},
    }


def _handoff(status: str) -> dict[str, Any]:
    job_status = {"READY": "SUCCEEDED", "BLOCKED": "FAILED"}[status]
    job = _job(job_status)
    generation = None
    content = None
    if status == "READY":
        text = "private generated answer"
        encoded = text.encode("utf-8")
        generation = {
            "cx_generation_id": "generation-1044",
            "status": "COMPLETED",
        }
        content = {
            "cx_generation_id": "generation-1044",
            "content_type": "text/plain",
            "content": text,
            "content_sha256": hashlib.sha256(encoded).hexdigest(),
            "size_bytes": len(encoded),
            "owner_scope_enforced": True,
        }
    return {
        "handoff_schema_version": "cx_generation_handoff.v1",
        "handoff_status": status,
        "next_action": {
            "READY": "PRESENT_GENERATION_TO_OWNER",
            "BLOCKED": "RETRY_OR_REPAIR_GENERATION",
        }[status],
        "job": job,
        "generation": generation,
        "content": content,
        "owner_scope_enforced": True,
    }


class FakeClient:
    def __init__(
        self,
        *,
        job: dict[str, Any] | None = None,
        handoff: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.job = job or _job()
        self.handoff = handoff
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_job(self, job_id: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("job", {"job_id": job_id, **kwargs}))
        if self.error is not None:
            raise self.error
        return self.job

    def get_handoff(self, job_id: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("handoff", {"job_id": job_id, **kwargs}))
        assert self.handoff is not None
        return self.handoff


@pytest.mark.parametrize("status", ["QUEUED", "RUNNING"])
def test_orchestration_polls_non_terminal_job_only(status: str) -> None:
    client = FakeClient(job=_job(status))

    result = orchestrate_generation_lifecycle(
        _record(),
        client=client,
        request_id="request-1044",
        trace_id="a" * 32,
    )

    assert result["lifecycle_orchestration_schema_version"] == (
        AE_GENERATION_LIFECYCLE_ORCHESTRATION_SCHEMA_VERSION
    )
    assert result["source"] == "CX_JOB"
    assert result["async_generation"]["cx_job_status"] == status
    assert result["progress"]["cx_job_status"] == status
    assert [call[0] for call in client.calls] == ["job"]
    assert client.calls[0][1]["tenant_id"] == "tenant-a"
    assert client.calls[0][1]["subject_id"] == "user-a"


def test_orchestration_converges_success_through_handoff_without_content() -> None:
    client = FakeClient(job=_job("SUCCEEDED"), handoff=_handoff("READY"))

    result = orchestrate_generation_lifecycle(
        _record(),
        client=client,
        request_id="request-1044",
        trace_id="b" * 32,
    )

    assert result["source"] == "CX_HANDOFF"
    assert result["changed"] is True
    assert result["async_generation"]["lifecycle_status"] == "COMPLETED"
    assert result["progress"]["progress_percent"] == 100
    assert result["content_included"] is False
    assert "private generated answer" not in json.dumps(result)
    assert [call[0] for call in client.calls] == ["job", "handoff"]


def test_orchestration_converges_failed_handoff() -> None:
    client = FakeClient(job=_job("FAILED"), handoff=_handoff("BLOCKED"))

    result = orchestrate_generation_lifecycle(
        _record(),
        client=client,
        request_id="request-1044",
        trace_id="c" * 32,
    )

    assert result["source"] == "CX_HANDOFF"
    assert result["async_generation"]["lifecycle_status"] == "BLOCKED"
    assert result["progress"]["recovery"]["action"] == "RETRY_AS_CHILD"


def test_terminal_cache_avoids_unnecessary_cx_request() -> None:
    record = _record("FAILED", retryable=False)
    client = FakeClient(error=AssertionError("must not call CX"))

    result = orchestrate_generation_lifecycle(
        record,
        client=client,
        request_id="request-1044",
        trace_id="d" * 32,
    )

    assert result["source"] == "AE_TERMINAL_CACHE"
    assert result["changed"] is False
    assert client.calls == []


def test_force_refresh_rechecks_terminal_state() -> None:
    record = _record("FAILED")
    client = FakeClient(job=_job("FAILED"), handoff=_handoff("BLOCKED"))

    result = orchestrate_generation_lifecycle(
        record,
        client=client,
        request_id="request-1044",
        trace_id="e" * 32,
        force_refresh=True,
    )

    assert result["source"] == "CX_HANDOFF"
    assert [call[0] for call in client.calls] == ["job", "handoff"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.clear(),
        lambda value: value.update(interaction_id=""),
        lambda value: value.update(tenant_id=None),
        lambda value: value.update(owner_user_id=" "),
        lambda value: value.update(generation=None),
        lambda value: value["generation"].update(async_generation={}),
    ],
)
def test_orchestration_rejects_invalid_record(mutation) -> None:
    record = _record()
    mutation(record)

    with pytest.raises(AeGenerationLifecycleError) as exc_info:
        orchestrate_generation_lifecycle(
            record,
            client=FakeClient(),
            request_id="request-1044",
            trace_id="f" * 32,
        )
    assert exc_info.value.status_code == 400


def test_orchestration_rejects_non_mapping_record() -> None:
    with pytest.raises(AeGenerationLifecycleError):
        orchestrate_generation_lifecycle(
            [],  # type: ignore[arg-type]
            client=FakeClient(),
            request_id="request-1044",
            trace_id="f" * 32,
        )


def test_client_failure_is_normalized() -> None:
    client = FakeClient(
        error=CxAsyncGenerationClientError(
            status_code=503,
            error_code="ae.cx_async_generation.unavailable",
            detail="CX is unavailable.",
            retryable=True,
        )
    )

    with pytest.raises(AeGenerationLifecycleError) as exc_info:
        orchestrate_generation_lifecycle(
            _record(),
            client=client,
            request_id="request-1044",
            trace_id="1" * 32,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.retryable is True
    assert str(exc_info.value) == "CX is unavailable."


def test_contract_failure_is_normalized() -> None:
    bad = _job("RUNNING")
    bad["job_id"] = "other-job"

    with pytest.raises(AeGenerationLifecycleError) as exc_info:
        orchestrate_generation_lifecycle(
            _record(),
            client=FakeClient(job=bad),
            request_id="request-1044",
            trace_id="2" * 32,
        )

    assert exc_info.value.error_code == "ae.generation_lifecycle.contract_invalid"
    assert exc_info.value.status_code == 422


def test_request_and_trace_ids_are_required_before_client_call() -> None:
    for request_id, trace_id in (("", "3" * 32), ("request", "")):
        client = FakeClient()
        with pytest.raises(AeGenerationLifecycleError):
            orchestrate_generation_lifecycle(
                _record(),
                client=client,
                request_id=request_id,
                trace_id=trace_id,
            )
        assert client.calls == []
