from __future__ import annotations

from copy import deepcopy

import pytest

from nex_cx.access_context import CxAccessContext
from nex_cx.mvp_integration import (
    CX_MVP_INTEGRATION_SCHEMA_VERSION,
    CxMvpIntegrationError,
    build_cx_mvp_integration_state,
    validate_cx_mvp_integration_state,
)


CONTEXT = CxAccessContext(
    caller_service_id="nex-ae-api",
    tenant_id="tenant-s100",
    subject_id="owner-s100",
    request_id="request-s100",
    trace_id="trace-s100",
    scopes=("service.invoke",),
)
SHA = "a" * 64


def _build(**overrides):
    values = {
        "access_context": CONTEXT,
        "document_id": "document-s100",
        "updated_at": "2026-09-27T00:00:00Z",
    }
    values.update(overrides)
    return build_cx_mvp_integration_state(**values)


@pytest.mark.parametrize(
    ("components", "expected"),
    [
        ({}, ("INGESTION", "IN_PROGRESS", "POLL_INGESTION")),
        ({"ingestion": {"id": "run", "status": "RUNNING"}}, ("INGESTION", "IN_PROGRESS", "POLL_INGESTION")),
        ({"ingestion": {"id": "run", "status": "FAILED"}}, ("INGESTION", "BLOCKED", "RETRY_INGESTION")),
        ({"ingestion": {"id": "run", "status": "CANCELLED"}}, ("INGESTION", "BLOCKED", "RETRY_INGESTION")),
        ({"ingestion": {"id": "run", "status": "SUCCEEDED"}}, ("INDEXING", "IN_PROGRESS", "POLL_INDEX")),
        ({"ingestion": {"id": "run", "status": "SUCCEEDED"}, "vector_index": {"id": "index", "status": "STALE"}}, ("INDEXING", "BLOCKED", "REBUILD_INDEX")),
        ({"ingestion": {"id": "run", "status": "SUCCEEDED"}, "vector_index": {"id": "index", "status": "FAILED"}}, ("INDEXING", "BLOCKED", "REBUILD_INDEX")),
        ({"ingestion": {"id": "run", "status": "SUCCEEDED"}, "vector_index": {"id": "index", "status": "READY"}}, ("RETRIEVAL", "READY", "CREATE_RETRIEVAL_PACKAGE")),
        ({"ingestion": {"id": "run", "status": "SUCCEEDED"}, "vector_index": {"id": "index", "status": "READY"}, "retrieval": {"id": "retrieval", "status": "NO_ANSWER", "sha256": SHA}}, ("RETRIEVAL", "BLOCKED", "REVISE_RETRIEVAL")),
        ({"ingestion": {"id": "run", "status": "SUCCEEDED"}, "vector_index": {"id": "index", "status": "READY"}, "retrieval": {"id": "retrieval", "status": "READY", "sha256": SHA}}, ("GENERATION", "READY", "CREATE_GENERATION_JOB")),
        ({"ingestion": {"id": "run", "status": "SUCCEEDED"}, "vector_index": {"id": "index", "status": "READY"}, "retrieval": {"id": "retrieval", "status": "PARTIAL", "sha256": SHA}, "generation_job": {"id": "job", "status": "RUNNING"}}, ("GENERATION", "IN_PROGRESS", "POLL_GENERATION_JOB")),
        ({"ingestion": {"id": "run", "status": "SUCCEEDED"}, "vector_index": {"id": "index", "status": "READY"}, "retrieval": {"id": "retrieval", "status": "READY", "sha256": SHA}, "generation_job": {"id": "job", "status": "SUCCEEDED"}}, ("GENERATION", "IN_PROGRESS", "POLL_GENERATION_RESULT")),
        ({"ingestion": {"id": "run", "status": "SUCCEEDED"}, "vector_index": {"id": "index", "status": "READY"}, "retrieval": {"id": "retrieval", "status": "READY", "sha256": SHA}, "generation_job": {"id": "job", "status": "FAILED"}}, ("GENERATION", "BLOCKED", "RETRY_OR_REPAIR_GENERATION")),
        ({"ingestion": {"id": "run", "status": "SUCCEEDED"}, "vector_index": {"id": "index", "status": "READY"}, "retrieval": {"id": "retrieval", "status": "READY", "sha256": SHA}, "generation": {"id": "generation", "status": "FAILED", "sha256": SHA}}, ("GENERATION", "BLOCKED", "RETRY_OR_REPAIR_GENERATION")),
        ({"ingestion": {"id": "run", "status": "SUCCEEDED"}, "vector_index": {"id": "index", "status": "READY"}, "retrieval": {"id": "retrieval", "status": "READY", "sha256": SHA}, "generation": {"id": "generation", "status": "RUNNING", "sha256": SHA}}, ("GENERATION", "IN_PROGRESS", "POLL_GENERATION_JOB")),
        ({"ingestion": {"id": "run", "status": "SUCCEEDED"}, "vector_index": {"id": "index", "status": "READY"}, "retrieval": {"id": "retrieval", "status": "READY", "sha256": SHA}, "generation": {"id": "generation", "status": "SUCCEEDED", "sha256": SHA}}, ("HANDOFF", "READY", "READ_GENERATION_HANDOFF")),
    ],
)
def test_mvp_integration_projects_lifecycle(components, expected) -> None:
    state = _build(**components)

    assert state["integration_schema_version"] == CX_MVP_INTEGRATION_SCHEMA_VERSION
    assert (state["stage"], state["status"], state["next_action"]) == expected
    assert state["tenant_ref"]["id"] == CONTEXT.tenant_id
    assert state["owner_subject_ref"]["id"] == CONTEXT.subject_id
    assert validate_cx_mvp_integration_state(state) == state


@pytest.mark.parametrize(
    "override",
    [
        {"document_id": ""},
        {"updated_at": ""},
        {"ingestion": {"id": "run", "status": "UNKNOWN"}},
        {"ingestion": {"id": "run", "status": "RUNNING", "text": "private"}},
        {"retrieval": {"id": "package", "status": "READY", "sha256": "bad"}},
    ],
)
def test_mvp_integration_rejects_invalid_inputs(override) -> None:
    with pytest.raises(CxMvpIntegrationError) as exc_info:
        _build(**override)
    assert exc_info.value.error_code == "cx.mvp_integration.invalid"
    assert str(exc_info.value)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda state: state.update(extra=True),
        lambda state: state.update(integration_schema_version="v0"),
        lambda state: state.update(stage="WRONG"),
        lambda state: state.update(tenant_ref={"type": "oa.user", "id": "x"}),
        lambda state: state.update(owner_subject_ref={"type": "oa.user", "id": ""}),
        lambda state: state.update(generation={"id": "g", "status": "SUCCEEDED"}),
    ],
)
def test_mvp_integration_validation_fails_closed(mutate) -> None:
    state = deepcopy(_build())
    mutate(state)
    with pytest.raises(CxMvpIntegrationError):
        validate_cx_mvp_integration_state(state)


def test_mvp_integration_identity_is_deterministic_and_owner_scoped() -> None:
    first = _build()
    replay = _build(updated_at="2026-09-27T01:00:00Z")
    other_owner = build_cx_mvp_integration_state(
        access_context=CxAccessContext(
            caller_service_id="nex-ae-api",
            tenant_id="tenant-s100",
            subject_id="owner-other",
            request_id="request-other",
            trace_id="trace-other",
            scopes=("service.invoke",),
        ),
        document_id="document-s100",
        updated_at="2026-09-27T00:00:00Z",
    )

    assert first["integration_id"] == replay["integration_id"]
    assert first["integration_id"] != other_owner["integration_id"]
