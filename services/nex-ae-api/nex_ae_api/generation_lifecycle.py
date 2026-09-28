from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from nex_ae_api.async_generation import (
    AeAsyncGenerationError,
    refresh_async_generation_job_projection,
    refresh_async_generation_projection,
    validate_async_generation_projection,
)
from nex_ae_api.cx_async_generation_client import (
    CxAsyncGenerationClient,
    CxAsyncGenerationClientError,
)
from nex_ae_api.generation_progress import (
    AeGenerationProgressError,
    build_generation_progress_projection,
)


AE_GENERATION_LIFECYCLE_ORCHESTRATION_SCHEMA_VERSION = (
    "ae_generation_lifecycle_orchestration.v1"
)
AE_GENERATION_CANCELLATION_ORCHESTRATION_SCHEMA_VERSION = (
    "ae_generation_cancellation_orchestration.v1"
)
_TERMINAL_LIFECYCLES = frozenset({"COMPLETED", "BLOCKED"})
_TERMINAL_CX_JOB_STATUSES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})


@dataclass(frozen=True)
class AeGenerationLifecycleError(Exception):
    error_code: str
    detail: str
    status_code: int = 422
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def orchestrate_generation_lifecycle(
    record: Mapping[str, Any],
    *,
    client: CxAsyncGenerationClient,
    request_id: str,
    trace_id: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    interaction_id, tenant_id, owner_user_id, current = _record_context(record)
    if current["lifecycle_status"] in _TERMINAL_LIFECYCLES and not force_refresh:
        return _result(
            interaction_id=interaction_id,
            previous=current,
            refreshed=current,
            source="AE_TERMINAL_CACHE",
        )
    try:
        job = client.get_job(
            current["job_id"],
            tenant_id=tenant_id,
            subject_id=owner_user_id,
            request_id=_required_text(request_id, "request_id"),
            trace_id=_required_text(trace_id, "trace_id"),
        )
        refreshed = refresh_async_generation_job_projection(current, job)
        source = "CX_JOB"
        if refreshed["cx_job_status"] in _TERMINAL_CX_JOB_STATUSES:
            handoff = client.get_handoff(
                refreshed["job_id"],
                tenant_id=tenant_id,
                subject_id=owner_user_id,
                request_id=request_id,
                trace_id=trace_id,
            )
            refreshed, _transient_content = refresh_async_generation_projection(
                refreshed, handoff
            )
            source = "CX_HANDOFF"
        return _result(
            interaction_id=interaction_id,
            previous=current,
            refreshed=refreshed,
            source=source,
        )
    except CxAsyncGenerationClientError as exc:
        raise AeGenerationLifecycleError(
            error_code=exc.error_code,
            detail=exc.detail,
            status_code=exc.status_code,
            retryable=exc.retryable,
        ) from exc
    except (AeAsyncGenerationError, AeGenerationProgressError) as exc:
        raise AeGenerationLifecycleError(
            error_code="ae.generation_lifecycle.contract_invalid",
            detail="Generation lifecycle state is inconsistent.",
            status_code=422,
            retryable=False,
        ) from exc


def orchestrate_generation_cancellation(
    record: Mapping[str, Any],
    *,
    client: CxAsyncGenerationClient,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    interaction_id, tenant_id, owner_user_id, current = _record_context(record)
    if current["cx_job_status"] == "CANCELLED":
        return _cancellation_result(
            interaction_id=interaction_id,
            previous=current,
            refreshed=current,
            outcome="ALREADY_CANCELLED",
            source="AE_TERMINAL_CACHE",
        )
    if current["lifecycle_status"] in _TERMINAL_LIFECYCLES:
        raise AeGenerationLifecycleError(
            error_code="ae.async_generation.not_cancellable",
            detail="Terminal asynchronous generation cannot be cancelled.",
            status_code=409,
        )
    normalized_request_id = _required_text(request_id, "request_id")
    normalized_trace_id = _required_text(trace_id, "trace_id")
    try:
        cancelled = client.cancel_job(
            current["job_id"],
            tenant_id=tenant_id,
            subject_id=owner_user_id,
            request_id=normalized_request_id,
            trace_id=normalized_trace_id,
        )
    except CxAsyncGenerationClientError as exc:
        if exc.status_code != 409 or exc.error_code != "job.transition_invalid":
            raise _client_error(exc) from exc
        reconciled = orchestrate_generation_lifecycle(
            record,
            client=client,
            request_id=normalized_request_id,
            trace_id=normalized_trace_id,
            force_refresh=True,
        )
        if reconciled["progress"]["terminal"] is not True:
            raise _client_error(exc) from exc
        return {
            **reconciled,
            "cancellation_orchestration_schema_version": (
                AE_GENERATION_CANCELLATION_ORCHESTRATION_SCHEMA_VERSION
            ),
            "outcome": "TERMINAL_STATE_WON",
        }
    try:
        refreshed = refresh_async_generation_job_projection(current, cancelled)
        return _cancellation_result(
            interaction_id=interaction_id,
            previous=current,
            refreshed=refreshed,
            outcome="CANCELLED",
            source="CX_CANCEL",
        )
    except (AeAsyncGenerationError, AeGenerationProgressError) as exc:
        raise AeGenerationLifecycleError(
            error_code="ae.async_generation.contract_invalid",
            detail="Generation cancellation state is inconsistent.",
            status_code=422,
        ) from exc


def _record_context(
    record: Mapping[str, Any],
) -> tuple[str, str, str, dict[str, Any]]:
    if not isinstance(record, Mapping):
        raise _invalid("Chat interaction must be an object.")
    interaction_id = _required_text(record.get("interaction_id"), "interaction_id")
    tenant_id = _required_text(record.get("tenant_id"), "tenant_id")
    owner_user_id = _required_text(record.get("owner_user_id"), "owner_user_id")
    generation = record.get("generation")
    async_generation = (
        generation.get("async_generation")
        if isinstance(generation, Mapping)
        else None
    )
    try:
        projection = validate_async_generation_projection(async_generation)
    except (AeAsyncGenerationError, TypeError) as exc:
        raise _invalid(
            "Chat interaction is not bound to valid asynchronous generation."
        ) from exc
    return interaction_id, tenant_id, owner_user_id, projection


def _result(
    *,
    interaction_id: str,
    previous: Mapping[str, Any],
    refreshed: Mapping[str, Any],
    source: str,
) -> dict[str, Any]:
    progress = build_generation_progress_projection(
        interaction_id=interaction_id,
        async_generation=refreshed,
    )
    return {
        "lifecycle_orchestration_schema_version": (
            AE_GENERATION_LIFECYCLE_ORCHESTRATION_SCHEMA_VERSION
        ),
        "interaction_id": interaction_id,
        "source": source,
        "changed": dict(previous) != dict(refreshed),
        "async_generation": deepcopy(dict(refreshed)),
        "progress": progress,
        "owner_scope_enforced": True,
        "content_included": False,
    }


def _cancellation_result(
    *,
    interaction_id: str,
    previous: Mapping[str, Any],
    refreshed: Mapping[str, Any],
    outcome: str,
    source: str,
) -> dict[str, Any]:
    return {
        **_result(
            interaction_id=interaction_id,
            previous=previous,
            refreshed=refreshed,
            source=source,
        ),
        "cancellation_orchestration_schema_version": (
            AE_GENERATION_CANCELLATION_ORCHESTRATION_SCHEMA_VERSION
        ),
        "outcome": outcome,
    }


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field_name} must be a non-empty string.")
    return value.strip()


def _invalid(detail: str) -> AeGenerationLifecycleError:
    return AeGenerationLifecycleError(
        error_code="ae.generation_lifecycle.request_invalid",
        detail=detail,
        status_code=400,
    )


def _client_error(exc: CxAsyncGenerationClientError) -> AeGenerationLifecycleError:
    return AeGenerationLifecycleError(
        error_code=exc.error_code,
        detail=exc.detail,
        status_code=exc.status_code,
        retryable=exc.retryable,
    )
