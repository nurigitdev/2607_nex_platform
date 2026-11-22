from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from mybee_ax.domain import (
    EosWorkAssignmentRequest,
    WorkAssignmentPlanLine,
    WorkforcePlanningError,
    admit_work_assignment_collection,
    admit_work_assignment_projection,
    build_work_assignment_list_request,
    build_work_assignment_request,
    work_assignment_payload_hash,
)
from nex_eos import project_work_assignment_payload_hash

TENANT_ID = "tenant-a"
PROJECT_ID = "c2000000-0000-4000-8000-000000000001"
WORK_SET_ID = "c3000000-0000-4000-8000-000000000001"
ASSIGNMENT_ID = "c4000000-0000-4000-8000-000000000001"
OPERATION_ID = "c5000000-0000-4000-8000-000000000001"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _line() -> WorkAssignmentPlanLine:
    return WorkAssignmentPlanLine(
        assignment_id=ASSIGNMENT_ID,
        work_set_id=WORK_SET_ID,
        work_set_revision=1,
        work_code_id="FL0012004",
        performer_kind="HUMAN",
        subject_ref="worker-a",
        assignment_scope="EXECUTE",
        planned_man_days=Decimal("10.5000"),
        planned_grade_id="G4",
        grade_policy_ref="mybee.grade-policy:2026.1",
        grade_policy_hash=HASH_A,
        valid_from=date(2026, 1, 1),
        valid_until=date(2026, 1, 31),
        approved_proof_hash=HASH_B,
    )


def _projection() -> dict[str, object]:
    return {
        "tenant_id": TENANT_ID,
        "assignment_id": ASSIGNMENT_ID,
        "project_id": PROJECT_ID,
        "work_set_id": WORK_SET_ID,
        "work_set_revision": 1,
        "work_code_id": "FL0012004",
        "performer_kind": "HUMAN",
        "subject_ref": "worker-a",
        "performer_authority_hash": HASH_A,
        "assignment_scope": "EXECUTE",
        "planned_man_days": "10.5000",
        "planned_grade_id": "G4",
        "grade_policy_ref": "mybee.grade-policy:2026.1",
        "grade_policy_hash": HASH_A,
        "valid_from": "2026-01-01",
        "valid_until": "2026-01-31",
        "approved_proof_hash": HASH_B,
        "approved_by_subject_id": "owner-a",
        "assignment_hash": HASH_B,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def test_request_builder_matches_eos_payload_hash_and_keeps_salary_out() -> None:
    request = build_work_assignment_request(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        requester_subject_id="owner-a",
        business_operation_id=OPERATION_ID,
        idempotency_key="s1-06:1",
        line=_line(),
    )
    assert isinstance(request, EosWorkAssignmentRequest)
    assert request.operation_id == "PROJECT.WORK_ASSIGNMENT.ASSIGN"
    assert request.payload is not None
    payload = {**request.payload, "project_id": PROJECT_ID}
    assert request.payload["payload_hash"] == work_assignment_payload_hash(payload)
    assert request.payload["payload_hash"] == project_work_assignment_payload_hash(
        payload
    )
    assert not {"salary", "actual_day_rate"}.intersection(request.payload["assignment"])


def test_list_request_and_projection_admission_are_tenant_project_scoped() -> None:
    request = build_work_assignment_list_request(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        requester_subject_id="owner-a",
        effective_on=date(2026, 1, 15),
        work_code_id="FL0012004",
    )
    assert request.query == {
        "effective_on": "2026-01-15",
        "work_code_id": "FL0012004",
    }
    projection = admit_work_assignment_projection(
        _projection(), tenant_id=TENANT_ID, project_id=PROJECT_ID
    )
    assert projection["planned_grade_id"] == "G4"
    collection = admit_work_assignment_collection(
        {
            "items": [_projection()],
            "count": 1,
            "data_classification": "INTERNAL_PLANNING",
            "private_payroll_excluded": True,
        },
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
    )
    assert collection == (projection,)

    empty_query = build_work_assignment_list_request(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        requester_subject_id="owner-a",
    )
    assert empty_query.query is None


@pytest.mark.parametrize(
    "line",
    (
        replace(_line(), planned_man_days=1.5),
        replace(_line(), planned_man_days=Decimal(0)),
        replace(_line(), planned_man_days=Decimal("1.00001")),
        replace(_line(), valid_from=date(2026, 2, 1)),
        replace(_line(), work_code_id="BAD"),
        replace(_line(), performer_kind="ROBOT"),
        replace(_line(), grade_policy_hash="bad"),
    ),
)
def test_request_builder_rejects_non_exact_or_drifted_plan(line) -> None:
    with pytest.raises(WorkforcePlanningError):
        build_work_assignment_request(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id="owner-a",
            business_operation_id=OPERATION_ID,
            idempotency_key="s1-06:invalid",
            line=line,
        )


def test_projection_and_collection_fail_closed_for_privacy_and_shape_drift() -> None:
    private = {**_projection(), "salary": "100000000"}
    with pytest.raises(WorkforcePlanningError):
        admit_work_assignment_projection(
            private, tenant_id=TENANT_ID, project_id=PROJECT_ID
        )
    incomplete = _projection()
    incomplete.pop("planned_grade_id")
    with pytest.raises(WorkforcePlanningError):
        admit_work_assignment_projection(
            incomplete, tenant_id=TENANT_ID, project_id=PROJECT_ID
        )


def test_transport_helpers_reject_untyped_inputs_and_bad_identities() -> None:
    with pytest.raises(WorkforcePlanningError):
        work_assignment_payload_hash("not-an-object")
    with pytest.raises(WorkforcePlanningError):
        build_work_assignment_request(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id="owner-a",
            business_operation_id=OPERATION_ID,
            idempotency_key="s1-06:bad-line",
            line="not-a-line",
        )
    for kwargs in (
        {"tenant_id": "bad tenant"},
        {"project_id": "bad-project"},
        {"requester_subject_id": ""},
        {"effective_on": datetime(2026, 1, 1, tzinfo=UTC)},
        {"work_code_id": "BAD"},
    ):
        values = {
            "tenant_id": TENANT_ID,
            "project_id": PROJECT_ID,
            "requester_subject_id": "owner-a",
            **kwargs,
        }
        with pytest.raises(WorkforcePlanningError):
            build_work_assignment_list_request(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("planned_man_days", "not-a-number"),
        ("planned_man_days", "100000000"),
        ("planned_man_days", True),
        ("planned_grade_id", ""),
        ("work_set_revision", 0),
        ("performer_kind", "ROBOT"),
        ("performer_authority_hash", "bad"),
        ("valid_from", 20260101),
        ("valid_from", "bad-date"),
        ("valid_until", "2025-12-31"),
        ("created_at", None),
        ("assignment_id", "bad-uuid"),
        ("subject_ref", "bad subject"),
    ),
)
def test_projection_field_validation_matrix(field, value) -> None:
    projection = {**_projection(), field: value}
    with pytest.raises(WorkforcePlanningError):
        admit_work_assignment_projection(
            projection, tenant_id=TENANT_ID, project_id=PROJECT_ID
        )


def test_collection_requires_object_and_list_payloads() -> None:
    with pytest.raises(WorkforcePlanningError):
        admit_work_assignment_collection(
            None, tenant_id=TENANT_ID, project_id=PROJECT_ID
        )
    with pytest.raises(WorkforcePlanningError):
        admit_work_assignment_collection(
            {
                "items": "not-a-list",
                "count": 0,
                "data_classification": "INTERNAL_PLANNING",
                "private_payroll_excluded": True,
            },
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
        )
    with pytest.raises(WorkforcePlanningError):
        admit_work_assignment_projection(
            _projection(), tenant_id="other-tenant", project_id=PROJECT_ID
        )
    with pytest.raises(WorkforcePlanningError):
        admit_work_assignment_collection(
            {
                "items": [_projection()],
                "count": 2,
                "data_classification": "INTERNAL_PLANNING",
                "private_payroll_excluded": True,
            },
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
        )
    with pytest.raises(WorkforcePlanningError):
        admit_work_assignment_collection(
            {
                "items": [],
                "count": 0,
                "data_classification": "PUBLIC",
                "private_payroll_excluded": False,
            },
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
        )
