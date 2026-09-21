from __future__ import annotations

import pytest

from nex_cx.access_context import CxAccessContext
from nex_cx.owner_lineage import (
    CX_OWNER_LINEAGE_SCHEMA_VERSION,
    CxOwnerLineage,
    CxOwnerLineageError,
    attach_owner_lineage,
    build_owner_lineage,
    normalize_owner_lineage,
    owner_lineage_matches_access_context,
)


def _context(*, tenant_id: str = "tenant-a", subject_id: str = "employee-1004"):
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id=tenant_id,
        subject_id=subject_id,
        request_id="request-0917",
        trace_id="91700000000000000000000000000001",
        scopes=("service:call",),
    )


def test_build_owner_lineage_exposes_canonical_wire_and_columns() -> None:
    lineage = build_owner_lineage(_context())

    assert lineage.ownership_key == ("tenant-a", "employee-1004")
    assert lineage.to_columns() == {
        "tenant_ref_type": "oa.tenant",
        "tenant_ref_id": "tenant-a",
        "owner_subject_ref_type": "oa.user",
        "owner_subject_ref_id": "employee-1004",
    }
    assert lineage.to_wire() == {
        "owner_lineage_schema_version": CX_OWNER_LINEAGE_SCHEMA_VERSION,
        "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
        "owner_subject_ref": {"type": "oa.user", "id": "employee-1004"},
    }


@pytest.mark.parametrize("wrapper", [False, True])
def test_normalize_owner_lineage_accepts_canonical_refs(wrapper: bool) -> None:
    value = {
        "tenant_ref": {"type": "oa.tenant", "id": " tenant-a "},
        "owner_subject_ref": {"type": "oa.user", "id": " employee-1004 "},
    }
    normalized = normalize_owner_lineage({"ownership_ref": value} if wrapper else value)

    assert normalized == build_owner_lineage(_context())
    assert normalize_owner_lineage(normalized) is normalized


def test_normalize_owner_lineage_accepts_flat_database_columns() -> None:
    normalized = normalize_owner_lineage(build_owner_lineage(_context()).to_columns())

    assert normalized.ownership_key == ("tenant-a", "employee-1004")


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"tenant_ref": {}, "owner_subject_ref": {}},
        {
            "tenant_ref": {"type": "workspace", "id": "tenant-a"},
            "owner_subject_ref": {"type": "oa.user", "id": "employee-1004"},
        },
        {
            "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
            "owner_subject_ref": {"type": "account", "id": "employee-1004"},
        },
        {
            "tenant_ref_type": "oa.tenant",
            "tenant_ref_id": "bad id",
            "owner_subject_ref_type": "oa.user",
            "owner_subject_ref_id": "employee-1004",
        },
    ],
)
def test_normalize_owner_lineage_rejects_noncanonical_values(value: object) -> None:
    with pytest.raises(CxOwnerLineageError) as caught:
        normalize_owner_lineage(value)

    assert caught.value.error_code == "CX_OWNER_LINEAGE_INVALID"
    assert caught.value.detail


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tenant_ref_type": "tenant"},
        {"owner_subject_ref_type": "user"},
        {"tenant_ref_id": 7},
        {"tenant_ref_id": ""},
        {"owner_subject_ref_id": "x" * 129},
    ],
)
def test_owner_lineage_constructor_validates_invariants(kwargs: dict[str, str]) -> None:
    values = {
        "tenant_ref_type": "oa.tenant",
        "tenant_ref_id": "tenant-a",
        "owner_subject_ref_type": "oa.user",
        "owner_subject_ref_id": "employee-1004",
        **kwargs,
    }
    with pytest.raises(CxOwnerLineageError):
        CxOwnerLineage(**values)


def test_attach_owner_lineage_adds_missing_and_accepts_matching_columns() -> None:
    lineage = build_owner_lineage(_context())

    attached = attach_owner_lineage({"status": "QUEUED"}, lineage)
    repeated = attach_owner_lineage(attached, lineage)

    assert attached["status"] == "QUEUED"
    assert repeated == attached
    assert owner_lineage_matches_access_context(_context(), attached) is True


def test_attach_owner_lineage_fails_closed_on_conflict() -> None:
    with pytest.raises(CxOwnerLineageError) as caught:
        attach_owner_lineage(
            {"owner_subject_ref_id": "employee-other"},
            build_owner_lineage(_context()),
        )

    assert caught.value.error_code == "CX_OWNER_LINEAGE_CONFLICT"
    assert owner_lineage_matches_access_context(_context(), {}) is False
    assert owner_lineage_matches_access_context(
        _context(),
        build_owner_lineage(_context(subject_id="employee-other")),
    ) is False
