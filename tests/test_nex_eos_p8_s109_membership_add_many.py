from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from nex_eos import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_METADATA,
    EOS_PROJECT_MEMBER_TABLE,
    PROJECT_CREATE_OPERATION,
    PROJECT_MEMBERSHIP_ADD_MANY_OPERATION,
    PROJECT_MEMBERSHIP_ADD_OPERATION,
    PROJECT_MEMBERSHIP_REMOVE_OPERATION,
    EosGovernedProjectError,
    EosGovernedProjectService,
    EosServiceCaller,
    NvtProjectInput,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosProjectRepository,
    deterministic_project_membership_id,
    project_membership_add_many_payload_hash,
    project_operation_payload_hash,
)
from nex_eos.authorization import AuthorizationSubjectDenied
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT_ID = "tenant-s109"
NVT_ID = "a9100000-0000-4000-8000-000000000001"
PROJECT_ID = "a9200000-0000-4000-8000-000000000001"
OWNER_ID = "owner-s109"
CALLER = EosServiceCaller("service:nex-ae-api", "nex-eos", ("service:call",))
ROOT = Path(__file__).resolve().parents[1]


class AuthorizationSource:
    def __init__(self) -> None:
        self.inactive: set[str] = set()
        self.ineligible: set[str] = set()
        self.absent: set[str] = set()
        self.unavailable: set[str] = set()

    def effective_authorization(
        self, *, tenant_id: str, subject_id: str
    ) -> Mapping[str, object]:
        if subject_id in self.unavailable:
            raise RuntimeError("private OA failure")
        if subject_id in self.absent:
            raise AuthorizationSubjectDenied(
                "missing",
                error_code="oa.authorization_membership_not_found",
            )
        return {
            "active": subject_id not in self.inactive,
            "eligible": subject_id not in self.ineligible,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": (
                [
                    "project:project:create",
                    "project:project:admin",
                    "project:membership:manage",
                ]
                if subject_id == OWNER_ID
                else []
            ),
            "revision_hash": "a" * 64,
        }


@pytest.fixture
def governed():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    projects = SqlAlchemyEosProjectRepository(factory)
    projects.create_nvt_project(
        NvtProjectInput(TENANT_ID, NVT_ID, "NVT-S109", "NVT S109")
    )
    source = AuthorizationSource()
    service = EosGovernedProjectService(
        session_factory=factory,
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(factory),
        authorization_source=source,
    )
    _create_project(service)
    return engine, factory, source, service


def _payload(operation: str, sequence: int, **values) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "eos_project_operation.v1",
        "tenant_id": TENANT_ID,
        "business_operation_id": f"a9300000-0000-4000-8000-{sequence:012d}",
        "idempotency_key": f"p8-s109-{sequence}",
        "requester_subject_id": OWNER_ID,
        **values,
    }
    payload["payload_hash"] = project_operation_payload_hash(payload, operation)
    return payload


def _create_project(service: EosGovernedProjectService) -> None:
    service.create_project(
        _payload(
            PROJECT_CREATE_OPERATION,
            1,
            project={
                "project_id": PROJECT_ID,
                "project_code": "PROJECT-S109",
                "name": "Project S109",
                "nvt_project_id": NVT_ID,
                "currency": "KRW",
            },
            initial_owner_subject_id=OWNER_ID,
            initial_owner_membership_id=(
                deterministic_project_membership_id(TENANT_ID, PROJECT_ID, OWNER_ID)
            ),
        ),
        caller=CALLER,
    )


def _add_single(
    service: EosGovernedProjectService,
    sequence: int,
    subject_id: str,
    role: str = "MEMBER",
) -> None:
    service.add_membership(
        _payload(
            PROJECT_MEMBERSHIP_ADD_OPERATION,
            sequence,
            project_id=PROJECT_ID,
            target_subject_id=subject_id,
            project_membership_id=deterministic_project_membership_id(
                TENANT_ID, PROJECT_ID, subject_id
            ),
            member_role=role,
        ),
        caller=CALLER,
    )


def _batch(sequence: int, subjects: list[str], role: str = "MEMBER"):
    payload = _payload(
        PROJECT_MEMBERSHIP_ADD_MANY_OPERATION,
        sequence,
        requested_operation=PROJECT_MEMBERSHIP_ADD_MANY_OPERATION,
        project_id=PROJECT_ID,
        target_subject_ids=sorted(subjects, key=lambda item: item.encode("utf-8")),
        member_role=role,
        resolution_evidence_hash=semantic_sha256_hash_ref(
            {"tenant_id": TENANT_ID, "subjects": sorted(subjects)}
        ),
    )
    payload["payload_hash"] = project_membership_add_many_payload_hash(payload)
    return payload


def test_add_many_commits_partial_item_outcomes_and_exact_replay(governed) -> None:
    _engine, _factory, source, service = governed
    _add_single(service, 2, "member-active")
    _add_single(service, 3, "member-reactivate")
    service.remove_membership(
        _payload(
            PROJECT_MEMBERSHIP_REMOVE_OPERATION,
            4,
            project_id=PROJECT_ID,
            target_subject_id="member-reactivate",
        ),
        caller=CALLER,
    )
    _add_single(service, 5, "member-role-conflict", "VIEWER")
    source.inactive.add("member-inactive")
    source.ineligible.add("member-ineligible")

    payload = _batch(
        6,
        [
            "member-new",
            "member-active",
            "member-reactivate",
            "member-role-conflict",
            "member-inactive",
            "member-ineligible",
        ],
    )
    committed = service.add_memberships(payload, caller=CALLER)
    replay = service.add_memberships(payload, caller=CALLER)

    assert committed["created"] is True
    assert replay["created"] is False
    assert replay["result"] == committed["result"]
    result = committed["result"]
    assert result["operation_status"] == "PARTIALLY_APPLIED"
    assert result["requested_count"] == 6
    assert result["resolved_count"] == 6
    assert result["added_count"] == 1
    assert result["reactivated_count"] == 1
    assert result["unchanged_count"] == 1
    assert result["rejected_count"] == 3
    assert {
        item["subject_id"]: item["outcome"] for item in result["item_results"]
    } == {
        "member-active": "ALREADY_ACTIVE",
        "member-inactive": "SUBJECT_INACTIVE",
        "member-ineligible": "NOT_ELIGIBLE",
        "member-new": "ADDED",
        "member-reactivate": "REACTIVATED",
        "member-role-conflict": "ROLE_CONFLICT",
    }


def test_no_change_and_all_rejected_results_are_durable(governed) -> None:
    _engine, factory, source, service = governed
    _add_single(service, 10, "member-active")
    unchanged = service.add_memberships(
        _batch(11, ["member-active"]), caller=CALLER
    )
    assert unchanged["result"]["operation_status"] == "NO_CHANGE"

    source.inactive.add("member-inactive")
    source.absent.add("member-absent")
    rejected = service.add_memberships(
        _batch(12, ["member-absent", "member-inactive"]), caller=CALLER
    )
    assert rejected["result"]["operation_status"] == "REJECTED"
    assert rejected["result"]["rejected_count"] == 2
    with factory() as session:
        assert session.execute(
            select(func.count()).select_from(EOS_BUSINESS_OPERATION_TABLE)
        ).scalar_one() == 4


def test_unavailable_oa_and_conflicting_replay_fail_closed(governed) -> None:
    _engine, factory, source, service = governed
    source.unavailable.add("member-unavailable")
    before = _operation_count(factory)
    with pytest.raises(EosGovernedProjectError) as unavailable:
        service.add_memberships(
            _batch(20, ["member-unavailable"]), caller=CALLER
        )
    assert unavailable.value.error_code == "EOS_PROJECT_AUTHORIZATION_UNAVAILABLE"
    assert unavailable.value.retryable is True
    assert _operation_count(factory) == before

    source.unavailable.clear()
    payload = _batch(21, ["member-a"])
    service.add_memberships(payload, caller=CALLER)
    conflict = _batch(21, ["member-b"])
    with pytest.raises(EosGovernedProjectError) as mismatch:
        service.add_memberships(conflict, caller=CALLER)
    assert mismatch.value.error_code == "EOS_IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update(target_subject_ids=[]),
        lambda value: value.update(target_subject_ids=["z", "a"]),
        lambda value: value.update(target_subject_ids=["a", "a"]),
        lambda value: value.update(member_role="BAD"),
        lambda value: value.update(resolution_evidence_hash="bad"),
        lambda value: value.update(payload_hash="sha256:" + "0" * 64),
    ),
)
def test_add_many_structural_and_hash_guards_fail_before_mutation(
    governed, mutate
) -> None:
    _engine, factory, _source, service = governed
    payload = _batch(30, ["member-a"])
    mutate(payload)
    if payload["payload_hash"] != "sha256:" + "0" * 64:
        try:
            payload["payload_hash"] = project_membership_add_many_payload_hash(payload)
        except EosGovernedProjectError:
            pass
    before = _operation_count(factory)
    with pytest.raises(EosGovernedProjectError):
        service.add_memberships(payload, caller=CALLER)
    assert _operation_count(factory) == before


def test_batch_membership_identity_matches_single_add_contract() -> None:
    assert deterministic_project_membership_id(
        TENANT_ID, PROJECT_ID, "member-a"
    ) == "1f690001-41c7-506f-a358-74b4718c0009"


def test_s108_admitted_payload_hash_is_the_s109_eos_hash() -> None:
    admission = json.loads(
        (
            ROOT
            / "contracts/examples/planning/ae_project_membership_batch_admission.mixed.json"
        ).read_text(encoding="utf-8")
    )
    assert project_membership_add_many_payload_hash(
        admission["governed_payload"]
    ) == admission["payload_hash"]


def _operation_count(factory) -> int:
    with factory() as session:
        return session.execute(
            select(func.count()).select_from(EOS_BUSINESS_OPERATION_TABLE)
        ).scalar_one()
