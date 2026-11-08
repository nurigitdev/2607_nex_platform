from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from nex_eos import (
    EOS_APPROVAL_LADDER,
    EOS_METADATA,
    EosApproverResolutionError,
    EosApproverResolutionService,
    OrgUnitInput,
    PositionAssignmentInput,
    PositionInput,
    SqlAlchemyEosOrganizationRepository,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 10, 23, 14, 0, tzinfo=UTC)
TENANT = "tenant-p8-s72"
INSTANCE_ID = "74000000-0000-4000-8000-000000000001"
POLICY_ID = "74000000-0000-4000-8000-000000000002"
ORG_ID = "74000000-0000-4000-8000-000000000003"
PROJECT_ID = "74000000-0000-4000-8000-000000000004"
POSITION_ID = "74000000-0000-4000-8000-000000000005"
ASSIGNMENT_ID = "74000000-0000-4000-8000-000000000006"


def _instance(route=("PART_LEAD",), *, active_order=1, **overrides):
    stages = [
        {
            "approval_stage_id": _stage_id(index),
            "stage_order": index,
            "position_type": position,
            "state": "ACTIVE" if index == active_order else "WAITING",
        }
        for index, position in enumerate(route, start=1)
    ]
    value = {
        "schema_version": "eos_approval_instance.v1",
        "tenant_id": TENANT,
        "approval_instance_id": INSTANCE_ID,
        "policy_ref": {
            "approval_policy_id": POLICY_ID,
            "version": 3,
            "policy_hash": "sha256:" + "1" * 64,
        },
        "approval_domain": "BUSINESS_FORMAL",
        "requester_ref": {"type": "oa.user", "id": "employee-requester"},
        "org_unit_ref": {"type": "eos.org_unit", "id": ORG_ID},
        "project_ref": {"type": "eos.project", "id": PROJECT_ID},
        "state": "PENDING",
        "active_stage_order": active_order,
        "stage_count": len(stages),
        "binding_hash": "sha256:" + "2" * 64,
        "stages": stages,
    }
    value.update(overrides)
    return value


def _stage(route=("PART_LEAD",), *, active_order=1, **overrides):
    value = {
        "schema_version": "eos_approval_stage.v1",
        "tenant_id": TENANT,
        "approval_stage_id": _stage_id(active_order),
        "approval_instance_id": INSTANCE_ID,
        "stage_order": active_order,
        "position_type": route[active_order - 1],
        "quorum_count": 1,
        "separation_policy": "REQUESTER_EXCLUDED",
        "state": "ACTIVE",
    }
    value.update(overrides)
    return value


def _stage_id(order: int) -> str:
    return f"74000000-0000-4000-8000-{100 + order:012d}"


def _assignment(position_type="PART_LEAD", principal="employee-approver"):
    return {
        "position_id": POSITION_ID,
        "position_type": position_type,
        "org_unit_id": ORG_ID,
        "position_assignment_id": ASSIGNMENT_ID,
        "principal_ref_type": "oa.user",
        "principal_id": principal,
        "position_assignment_version": 4,
        "org_unit_version": 2,
    }


class AssignmentSource:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def resolve_active_approver_assignment(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


@pytest.mark.parametrize(
    ("route", "active_order"),
    (
        (("PART_LEAD",), 1),
        (("PART_LEAD", "TEAM_LEAD"), 1),
        (("TEAM_LEAD", "GROUP_LEAD", "CEO"), 2),
        (EOS_APPROVAL_LADDER, 5),
    ),
)
def test_resolves_one_two_and_multi_stage_ordered_policy_subsets(
    route, active_order
) -> None:
    position_type = route[active_order - 1]
    source = AssignmentSource(_assignment(position_type))
    result = EosApproverResolutionService(
        source, clock=lambda: NOW
    ).resolve_active_stage(
        instance=_instance(route, active_order=active_order),
        stage=_stage(route, active_order=active_order),
    )

    assert result["leadership_route"] == list(route)
    assert result["stage_order"] == active_order
    assert result["stage_count"] == len(route)
    assert result["position_type"] == position_type
    assert result["principal_ref"] == {
        "type": "oa.user",
        "id": "employee-approver",
    }
    assert result["position_assignment_version"] == 4
    assert result["org_unit_version"] == 2
    assert result["security_authorization"] is False
    assert source.calls == [
        {
            "tenant_id": TENANT,
            "org_unit_id": ORG_ID,
            "position_type": position_type,
            "effective_at": NOW,
        }
    ]


def test_stage_resolution_hash_is_time_independent_and_assignment_bound() -> None:
    source = AssignmentSource(_assignment())
    first = EosApproverResolutionService(
        source, clock=lambda: NOW
    ).resolve_active_stage(instance=_instance(), stage=_stage())
    second = EosApproverResolutionService(
        source, clock=lambda: NOW + timedelta(minutes=5)
    ).resolve_active_stage(instance=_instance(), stage=_stage())

    assert first["resolution_hash"] == second["resolution_hash"]
    assert first["resolution_ref"] == second["resolution_ref"]
    assert first["resolved_at"] != second["resolved_at"]
    assert first["resolution_ref"].endswith(
        first["resolution_hash"].removeprefix("sha256:")
    )


def test_actual_organization_repository_resolves_effective_stage_assignment() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    repository = SqlAlchemyEosOrganizationRepository(
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    )
    repository.create_org_unit(
        OrgUnitInput(
            TENANT,
            ORG_ID,
            "P8-S72-FINANCE",
            "P8 S72 Finance",
            "TEAM",
            NOW - timedelta(days=1),
        )
    )
    repository.create_position(PositionInput(TENANT, POSITION_ID, "TEAM_LEAD", ORG_ID))
    repository.assign_position(
        PositionAssignmentInput(
            TENANT,
            ASSIGNMENT_ID,
            POSITION_ID,
            {"type": "oa.user", "id": "employee-sqlite-approver"},
            NOW - timedelta(hours=1),
        )
    )

    result = EosApproverResolutionService(
        repository, clock=lambda: NOW
    ).resolve_active_stage(
        instance=_instance(("PART_LEAD", "TEAM_LEAD"), active_order=2),
        stage=_stage(("PART_LEAD", "TEAM_LEAD"), active_order=2),
    )

    assert result["principal_ref"]["id"] == "employee-sqlite-approver"
    assert result["position_type"] == "TEAM_LEAD"


def test_missing_assignment_and_requester_self_approval_fail_closed() -> None:
    with pytest.raises(EosApproverResolutionError) as missing:
        EosApproverResolutionService(
            AssignmentSource(), clock=lambda: NOW
        ).resolve_active_stage(instance=_instance(), stage=_stage())
    assert (missing.value.error_code, missing.value.status_code) == (
        "EOS_APPROVER_NOT_FOUND",
        404,
    )

    with pytest.raises(EosApproverResolutionError) as self_approval:
        EosApproverResolutionService(
            AssignmentSource(_assignment(principal="employee-requester")),
            clock=lambda: NOW,
        ).resolve_active_stage(instance=_instance(), stage=_stage())
    assert (self_approval.value.error_code, self_approval.value.status_code) == (
        "EOS_APPROVER_SELF_ASSIGNMENT",
        409,
    )


@pytest.mark.parametrize(
    ("instance_change", "stage_change"),
    (
        ({"approval_domain": "NSL_WRITE"}, {}),
        ({"state": "APPROVED"}, {}),
        ({"stage_count": 2}, {}),
        ({"active_stage_order": 2}, {}),
        ({"stages": "PART_LEAD"}, {}),
        ({"stages": []}, {}),
        ({"stages": [42]}, {}),
        (
            {
                "stages": [{"stage_order": 2, "position_type": "PART_LEAD"}],
            },
            {},
        ),
        (
            {
                "stages": [{"stage_order": 1, "position_type": "DIRECTOR"}],
            },
            {},
        ),
        (
            {
                "stages": [
                    {"stage_order": 1, "position_type": "TEAM_LEAD"},
                    {"stage_order": 2, "position_type": "PART_LEAD"},
                ],
                "stage_count": 2,
            },
            {},
        ),
        (
            {
                "stages": [
                    {"stage_order": 1, "position_type": "PART_LEAD"},
                    {"stage_order": 2, "position_type": "PART_LEAD"},
                ],
                "stage_count": 2,
            },
            {},
        ),
        ({}, {"tenant_id": "other-tenant"}),
        ({}, {"state": "WAITING"}),
        ({}, {"position_type": "TEAM_LEAD"}),
        ({}, {"quorum_count": 2}),
        ({}, {"separation_policy": "ALLOW_SELF"}),
    ),
)
def test_invalid_instance_route_and_active_stage_fail_closed(
    instance_change, stage_change
) -> None:
    instance = _instance()
    instance.update(instance_change)
    stage = _stage()
    stage.update(stage_change)

    with pytest.raises(EosApproverResolutionError) as error:
        EosApproverResolutionService(
            AssignmentSource(_assignment()), clock=lambda: NOW
        ).resolve_active_stage(instance=instance, stage=stage)

    assert error.value.error_code == "EOS_APPROVER_RESOLUTION_INVALID"
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    "assignment_change",
    (
        {"principal_ref_type": "oa.service"},
        {"principal_id": "bad principal"},
        {"position_type": "CEO"},
        {"org_unit_id": "74000000-0000-4000-8000-000000000099"},
        {"position_id": "not-a-uuid"},
        {"position_assignment_version": 0},
        {"org_unit_version": True},
    ),
)
def test_malformed_or_mismatched_assignment_fails_closed(assignment_change) -> None:
    assignment = _assignment()
    assignment.update(assignment_change)

    with pytest.raises(EosApproverResolutionError) as error:
        EosApproverResolutionService(
            AssignmentSource(assignment), clock=lambda: NOW
        ).resolve_active_stage(instance=_instance(), stage=_stage())

    assert (error.value.error_code, error.value.status_code) == (
        "EOS_APPROVER_RESOLUTION_INVALID_STATE",
        409,
    )


def test_incomplete_assignment_and_non_object_inputs_fail_closed() -> None:
    incomplete = _assignment()
    incomplete.pop("position_id")
    with pytest.raises(EosApproverResolutionError) as incomplete_error:
        EosApproverResolutionService(
            AssignmentSource(incomplete), clock=lambda: NOW
        ).resolve_active_stage(instance=_instance(), stage=_stage())
    assert incomplete_error.value.error_code == "EOS_APPROVER_RESOLUTION_INVALID_STATE"

    service = EosApproverResolutionService(
        AssignmentSource(_assignment()), clock=lambda: NOW
    )
    with pytest.raises(EosApproverResolutionError):
        service.resolve_active_stage(instance=[], stage=_stage())  # type: ignore[arg-type]
    with pytest.raises(EosApproverResolutionError):
        service.resolve_active_stage(instance=_instance(), stage=[])  # type: ignore[arg-type]


def test_policy_binding_is_strictly_validated() -> None:
    for policy_ref in (
        {},
        {
            "approval_policy_id": POLICY_ID,
            "version": 0,
            "policy_hash": "sha256:" + "1" * 64,
        },
        {
            "approval_policy_id": POLICY_ID,
            "version": 1,
            "policy_hash": "not-a-hash",
        },
    ):
        instance = deepcopy(_instance())
        instance["policy_ref"] = policy_ref
        with pytest.raises(EosApproverResolutionError):
            EosApproverResolutionService(
                AssignmentSource(_assignment()), clock=lambda: NOW
            ).resolve_active_stage(instance=instance, stage=_stage())
