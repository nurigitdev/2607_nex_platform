from __future__ import annotations

from copy import deepcopy

import pytest
from nex_cx.access_context import CxAccessContext
from nex_cx.async_generation_contracts import (
    AsyncGenerationContractError,
    CX_ASYNC_GENERATION_JOB_TYPE,
    async_generation_job_id,
    build_async_generation_job,
    project_async_generation_job,
    validate_async_generation_job,
)
from nex_cx import async_generation_contracts as contracts


def _context() -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id="tenant-1",
        subject_id="user-1",
        request_id="request-1",
        trace_id="trace-1",
        scopes=("service:call",),
    )


def _job() -> dict[str, object]:
    return build_async_generation_job(
        cx_generation_id="generation-1",
        admission_id="admission-1",
        access_context=_context(),
        request_envelope_sha256="a" * 64,
        request_envelope_size_bytes=128,
        trace_id="trace-1",
        request_id="request-1",
        created_at="2026-09-24T00:00:00Z",
    )


def test_builds_deterministic_metadata_only_job() -> None:
    first = _job()
    second = _job()

    assert first == second
    assert first["job_type"] == CX_ASYNC_GENERATION_JOB_TYPE
    assert first["job_id"] == async_generation_job_id("generation-1")
    assert first["max_attempts"] == 3
    assert first["payload"] == {
        "async_generation_schema_version": "cx_async_generation_job.v1",
        "cx_generation_id": "generation-1",
        "admission_id": "admission-1",
        "tenant_ref_id": "tenant-1",
        "owner_subject_ref_id": "user-1",
        "request_envelope_sha256": "a" * 64,
        "request_envelope_size_bytes": 128,
    }


def test_projects_only_owner_safe_job_state() -> None:
    job = _job()
    job["error"] = {
        "error_code": "provider.timeout",
        "detail": "private provider detail",
        "retryable": True,
        "dead_lettered": False,
    }

    projected = project_async_generation_job(job)

    assert "payload" not in projected
    assert "detail" not in projected["error"]
    assert projected["error"] == {
        "error_code": "provider.timeout",
        "retryable": True,
        "dead_lettered": False,
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda job: job.update(job_type="wrong"), "type is invalid"),
        (lambda job: job.pop("payload"), "payload is required"),
        (
            lambda job: job["payload"].update(async_generation_schema_version="v0"),
            "schema version",
        ),
        (lambda job: job.update(job_id="wrong"), "identity is invalid"),
        (
            lambda job: job.update(subject_ref={"type": "oa.user", "id": "other"}),
            "owner binding",
        ),
        (lambda job: job["payload"].update(prompt_text="secret"), "private request"),
        (
            lambda job: job["payload"].update(request_envelope_sha256="ABC"),
            "lowercase SHA-256",
        ),
        (
            lambda job: job["payload"].update(request_envelope_size_bytes=0),
            "positive integer",
        ),
    ],
)
def test_rejects_invalid_or_private_jobs(mutation, message: str) -> None:
    job = deepcopy(_job())
    mutation(job)

    with pytest.raises(AsyncGenerationContractError, match=message):
        validate_async_generation_job(job)


@pytest.mark.parametrize("field", ["cx_generation_id", "admission_id"])
def test_rejects_blank_identity_fields(field: str) -> None:
    values = {
        "cx_generation_id": "generation-1",
        "admission_id": "admission-1",
    }
    values[field] = " "

    with pytest.raises(AsyncGenerationContractError, match=field):
        build_async_generation_job(
            **values,
            access_context=_context(),
            request_envelope_sha256="a" * 64,
            request_envelope_size_bytes=1,
            trace_id="trace-1",
            request_id="request-1",
        )


def test_rejects_non_mapping_and_invalid_attempt_count() -> None:
    with pytest.raises(AsyncGenerationContractError, match="must be an object"):
        validate_async_generation_job([])  # type: ignore[arg-type]
    with pytest.raises(AsyncGenerationContractError, match="max_attempts"):
        build_async_generation_job(
            cx_generation_id="generation-1",
            admission_id="admission-1",
            access_context=_context(),
            request_envelope_sha256="a" * 64,
            request_envelope_size_bytes=1,
            trace_id="trace-1",
            request_id="request-1",
            max_attempts=True,
        )


def test_projection_without_error_is_stable() -> None:
    assert project_async_generation_job(_job())["error"] is None
    assert str(AsyncGenerationContractError("code", "detail")) == "detail"
    assert contracts._contains_private_payload(["safe"]) is False
    assert contracts._contains_private_payload([{"api_key": "secret"}]) is True
