from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace

from fastapi import Request
import pytest

from nex_runtime import issue_mock_service_token
from nex_cx.access_context import CxAccessContext
from nex_cx.api_ownership import (
    CxApiOwnershipError,
    content_object_visible_to_owner,
    document_visible_to_owner,
    owner_scoped_record,
    record_visible_to_owner,
    require_optional_owner_aliases_match,
    require_owner_assertion_match,
)
from nex_cx.authorization import authorize_cx_owner_request


NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _context(subject_id: str = "employee-0918") -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id="tenant-s92",
        subject_id=subject_id,
        request_id="request-0918",
        trace_id="91800000000000000000000000000001",
        scopes=("service:call",),
    )


def _request(*, traceparent: str | None = None) -> Request:
    headers = [(b"x-request-id", b"request-0918")]
    if traceparent is not None:
        headers.append((b"traceparent", traceparent.encode()))
    else:
        headers.append((b"x-trace-id", b"91800000000000000000000000000001"))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/documents/doc-0918",
            "raw_path": b"/api/v1/documents/doc-0918",
            "query_string": b"",
            "headers": headers,
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
        }
    )


def _authorization(service_id: str = "nex-ae-api") -> str:
    issued = issue_mock_service_token(
        service_id=service_id,
        audience="nex-cx",
        issued_at=NOW,
    )
    return f"Bearer {issued.access_token}"


def test_owner_guard_resolves_and_attaches_canonical_context() -> None:
    request = _request(traceparent="00-91800000000000000000000000000001-00f067aa0ba902b7-01")

    context = authorize_cx_owner_request(
        request,
        _authorization(),
        tenant_id="tenant-s92",
        subject_id="employee-0918",
        now=NOW + timedelta(seconds=1),
    )

    assert isinstance(context, CxAccessContext)
    assert context.ownership_key == ("tenant-s92", "employee-0918")
    assert request.state.cx_access_context is context
    assert request.state.cx_caller_service_id == "nex-ae-api"
    assert request.state.cx_caller_scopes == ("service:call",)


@pytest.mark.parametrize(
    ("tenant_id", "subject_id", "error_code"),
    [
        (None, "employee-0918", "CX_ACCESS_CONTEXT_INVALID"),
        ("tenant-s92", " ", "CX_ACCESS_CONTEXT_INVALID"),
    ],
)
def test_owner_guard_fails_closed_for_missing_owner_headers(
    tenant_id: object,
    subject_id: object,
    error_code: str,
) -> None:
    response = authorize_cx_owner_request(
        _request(),
        _authorization(),
        tenant_id=tenant_id,
        subject_id=subject_id,
        now=NOW + timedelta(seconds=1),
    )

    assert response.status_code == 422
    assert json.loads(response.body)["error_code"] == error_code


def test_owner_assertions_and_aliases_reject_cross_owner_access() -> None:
    context = _context()
    lineage = require_owner_assertion_match(
        context,
        {
            "tenant_ref_type": "oa.tenant",
            "tenant_ref_id": "tenant-s92",
            "owner_subject_ref_type": "oa.user",
            "owner_subject_ref_id": "employee-0918",
        },
    )
    assert lineage.ownership_key == context.ownership_key
    require_optional_owner_aliases_match(context)
    require_optional_owner_aliases_match(
        context,
        tenant_id=" tenant-s92 ",
        owner_user_id=" employee-0918 ",
    )

    with pytest.raises(CxApiOwnershipError) as mismatch:
        require_owner_assertion_match(
            context,
            {
                "tenant_ref_type": "oa.tenant",
                "tenant_ref_id": "tenant-s92",
                "owner_subject_ref_type": "oa.user",
                "owner_subject_ref_id": "other-user",
            },
        )
    assert mismatch.value.error_code == "cx.owner_scope_mismatch"

    for aliases in (
        {"tenant_id": None, "owner_user_id": "employee-0918"},
        {"tenant_id": "tenant-s92", "owner_user_id": " "},
        {"tenant_id": "tenant-s92", "owner_user_id": "other-user"},
    ):
        with pytest.raises(CxApiOwnershipError):
            require_optional_owner_aliases_match(context, **aliases)


def test_owner_visibility_requires_active_canonical_lineage() -> None:
    context = _context()
    owned = owner_scoped_record(context, {"document_id": "doc-0918"})
    active = {**owned, "lifecycle_status": "ACTIVE"}

    assert record_visible_to_owner(context, owned)
    assert not record_visible_to_owner(_context("other-user"), owned)
    assert not record_visible_to_owner(context, None)
    assert not record_visible_to_owner(context, {"document_id": "legacy"})
    assert content_object_visible_to_owner(context, active)
    assert not content_object_visible_to_owner(
        context,
        {**active, "lifecycle_status": "DELETED"},
    )

    repository = SimpleNamespace(get_content_object=lambda document_id: active)
    assert document_visible_to_owner(
        context,
        SimpleNamespace(content_repository=repository),
        "doc-0918",
    )
    assert not document_visible_to_owner(context, object(), "doc-0918")
