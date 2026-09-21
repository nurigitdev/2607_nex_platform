from __future__ import annotations

import pytest

from nex_cx.access_context import CxAccessContext
from nex_cx.retrieval_permissions import (
    PERMISSION_POLICY_ID,
    RetrievalPermissionError,
    build_evidence_permission_result,
    build_permission_snapshot,
    evaluate_retrieval_permission,
    filter_retrieval_document_scope,
)


def context(tenant: str = "tenant-a", subject: str = "owner-a") -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id=tenant,
        subject_id=subject,
        request_id="request-a",
        trace_id="a" * 32,
        scopes=("service:call",),
    )


def content(
    *,
    tenant: str = "tenant-a",
    subject: str = "owner-a",
    status: str = "ACTIVE",
) -> dict[str, object]:
    return {
        "lifecycle_status": status,
        "ownership_ref": {
            "ownership_schema_version": "cx_source_ownership_ref.v1",
            "tenant_ref": {"type": "oa.tenant", "id": tenant},
            "owner_subject_ref": {"type": "oa.user", "id": subject},
            "uploaded_by_subject_ref": {"type": "oa.user", "id": subject},
            "legacy": {
                "tenant_id": tenant,
                "owner_user_id": subject,
                "uploaded_by_user_id": subject,
            },
        },
    }


def test_permission_decision_allows_only_active_exact_owner() -> None:
    allowed = evaluate_retrieval_permission(context(), content())

    assert allowed == {
        "permission_decision_schema_version": "cx_retrieval_permission_decision.v1",
        "visible": True,
        "reason": "PRIVATE_OWNER_ACTIVE",
        "policy_version": PERMISSION_POLICY_ID,
    }


@pytest.mark.parametrize(
    "candidate",
    [
        None,
        "bad",
        content(subject="owner-b"),
        content(tenant="tenant-b"),
        content(status="DELETED"),
    ],
)
def test_denied_decisions_are_indistinguishable(candidate: object) -> None:
    denied = evaluate_retrieval_permission(context(), candidate)

    assert denied["visible"] is False
    assert denied["reason"] == "RESOURCE_NOT_FOUND"
    assert denied["policy_version"] == PERMISSION_POLICY_ID


def test_filter_deduplicates_and_measures_scope() -> None:
    result = filter_retrieval_document_scope(
        access_context=context(),
        requested_document_ids=["doc-a", " doc-a ", "doc-b"],
        content_objects={"doc-a": content(), "doc-b": content()},
    )

    assert result["requested_document_count"] == 2
    assert result["visible_document_ids"] == ["doc-a", "doc-b"]
    assert result["visible_document_count"] == 2
    assert result["filtered_document_count"] == 0
    assert result["filtered_chunk_count"] == 0


def test_explicit_scope_fails_closed_without_denied_identifier() -> None:
    with pytest.raises(RetrievalPermissionError) as captured:
        filter_retrieval_document_scope(
            access_context=context(),
            requested_document_ids=["doc-a", "secret-doc"],
            content_objects={"doc-a": content(), "secret-doc": content(subject="owner-b")},
        )

    assert captured.value.status_code == 404
    assert captured.value.error_code == "cx.document_scope_not_found"
    assert "secret-doc" not in captured.value.detail


def test_filter_can_return_internal_denied_count_without_loading_chunks() -> None:
    result = filter_retrieval_document_scope(
        access_context=context(),
        requested_document_ids=["doc-a", "doc-b", "missing"],
        content_objects={"doc-a": content(), "doc-b": content(subject="owner-b")},
        require_all_visible=False,
    )

    assert result["visible_document_ids"] == ["doc-a"]
    assert result["filtered_document_count"] == 2
    assert result["filtered_chunk_count"] == 0
    assert result["chunk_filter_semantics"] == "denied_documents_not_expanded"


@pytest.mark.parametrize(
    "document_ids",
    ["doc-a", [""], [None]],
)
def test_filter_rejects_invalid_document_ids(document_ids: object) -> None:
    with pytest.raises(RetrievalPermissionError) as captured:
        filter_retrieval_document_scope(
            access_context=context(),
            requested_document_ids=document_ids,  # type: ignore[arg-type]
            content_objects={},
        )

    assert captured.value.status_code == 422
    assert captured.value.error_code == "cx.document_scope_invalid"


def test_snapshot_uses_authenticated_identity_and_measured_counts() -> None:
    filter_result = filter_retrieval_document_scope(
        access_context=context(),
        requested_document_ids=["doc-a"],
        content_objects={"doc-a": content()},
    )

    snapshot = build_permission_snapshot(
        access_context=context(),
        scope_type="explicit_document_ids",
        filter_result=filter_result,
    )

    assert snapshot["actor_type"] == "oa.user"
    assert snapshot["actor_id"] == "owner-a"
    assert snapshot["tenant_ref"] == {"type": "oa.tenant", "id": "tenant-a"}
    assert snapshot["scope_requested"]["document_count"] == 1
    assert snapshot["scope_applied"]["document_ids"] == ["doc-a"]
    assert snapshot["classification_filter"] == ["private_owner"]
    assert snapshot["policy_version"] == PERMISSION_POLICY_ID


@pytest.mark.parametrize(
    ("updates", "expected_detail"),
    [
        ({"visible_document_ids": "bad"}, "Visible document IDs"),
        ({"visible_document_count": -1}, "visible_document_count"),
        ({"visible_document_count": 0}, "Visible document count"),
        ({"requested_document_count": 2}, "Requested document count"),
        ({"filtered_chunk_count": True}, "filtered_chunk_count"),
    ],
)
def test_snapshot_rejects_inconsistent_filter_results(
    updates: dict[str, object],
    expected_detail: str,
) -> None:
    result: dict[str, object] = {
        "requested_document_count": 1,
        "visible_document_ids": ["doc-a"],
        "visible_document_count": 1,
        "filtered_document_count": 0,
        "filtered_chunk_count": 0,
        "chunk_filter_semantics": "denied_documents_not_expanded",
    }
    result.update(updates)

    with pytest.raises(RetrievalPermissionError) as captured:
        build_permission_snapshot(
            access_context=context(),
            scope_type="explicit_document_ids",
            filter_result=result,
        )

    assert expected_detail in captured.value.detail


def test_snapshot_rejects_unknown_scope_type() -> None:
    with pytest.raises(RetrievalPermissionError):
        build_permission_snapshot(
            access_context=context(),
            scope_type="shared_documents",
            filter_result={
                "requested_document_count": 0,
                "visible_document_ids": [],
                "visible_document_count": 0,
                "filtered_document_count": 0,
                "filtered_chunk_count": 0,
            },
        )


def test_evidence_result_requires_visible_current_policy_decision() -> None:
    allowed = evaluate_retrieval_permission(context(), content())
    assert build_evidence_permission_result(allowed) == {
        "visible": True,
        "reason": "PRIVATE_OWNER_ACTIVE",
        "policy_version": PERMISSION_POLICY_ID,
    }

    with pytest.raises(RetrievalPermissionError):
        build_evidence_permission_result(
            evaluate_retrieval_permission(context(), None)
        )
    with pytest.raises(RetrievalPermissionError):
        build_evidence_permission_result(
            {"visible": True, "policy_version": "stale-policy"}
        )
